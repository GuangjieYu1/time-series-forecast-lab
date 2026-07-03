export type InferredType = "datetime" | "number" | "boolean" | "string" | "empty";

export interface ColumnProfile {
  name: string;
  inferredType: InferredType;
  sampleValues: unknown[];
  nonNullCountInPreview: number;
  nullCountInPreview: number;
}

export interface SheetPreview {
  sheetName: string;
  rowCountApprox: number | null;
  columns: ColumnProfile[];
  previewRows: Record<string, unknown>[];
}

export interface UploadPreviewResponse {
  uploadId: string;
  fileName: string;
  fileSize: number;
  fileSha256: string;
  sheets: SheetPreview[];
}

export interface ModelCapability {
  id: string;
  name: string;
  category: string;
  shortDescription: string;
  representativePaperTitle: string | null;
  representativePaperUrl: string | null;
  supportsUnivariate: boolean;
  supportsMultipleTargets: boolean;
  supportsCovariates: boolean;
  supportsPredictionInterval: boolean;
  minHorizon: number;
  maxHorizon: number;
  requiresGpu: boolean;
  isFoundationModel: boolean;
  enabledInMvp: boolean;
  availabilityStatus: "available" | "downloading" | "unavailable";
  unavailableReason: string | null;
  installStatus: "available" | "not_installed" | "downloading" | "planned" | "failed";
  dependencyPackage: string | null;
  installCommand: string | null;
  paperTitle: string | null;
  paperUrl: string | null;
  modelFamily: string;
  priority: number;
}

export interface DeviceInfo {
  device: string;
  memoryTotalMb: number | null;
  memoryAvailableMb: number | null;
}

export interface MetricValues {
  mae: number | null;
  mse: number | null;
  rmse: number | null;
  wape: number | null;
}

export interface RankedModel {
  modelId: string;
  modelName: string;
  rank: number | null;
  metrics: MetricValues | null;
  runtime: {
    fitSeconds: number;
    predictSeconds: number;
  };
  status: "success" | "failed";
  warnings: string[];
  error: string | null;
  tuning: {
    enabled: boolean;
    profile: "fast" | "balanced" | "accurate";
    strategy: "default" | "auto";
    strategyLabel: string;
    sampler: string | null;
    pruner: string | null;
    selectedParams: Record<string, number | string | boolean>;
    candidateCount: number;
    bestMetric: number | null;
    tuningSeconds: number;
    candidateLimit: number;
    timeBudgetSeconds: number;
    validationSize: number;
    stoppedEarly: boolean;
    trials: {
      round: number;
      params: Record<string, number | string | boolean>;
      status: "running" | "success" | "failed" | "pruned";
      metrics: MetricValues | null;
      elapsedSeconds: number;
      selected: boolean;
      message: string | null;
    }[];
    warnings: string[];
  } | null;
}

export interface BacktestPredictionPoint {
  time: string;
  predicted: number;
  actual: number;
  residual: number;
  absoluteError: number;
  squaredError: number;
}

export interface Diagnostics {
  originalRowCount: number;
  validRowCount: number;
  droppedRowCount: number;
  duplicateTimeCount: number;
  missingTimeCount: number;
  invalidTimeCount: number;
  inputMissingTargetCount: number;
  invalidTargetCount: number;
  filledValueCount: number;
  outlierCount: number;
  outlierAdjustedCount: number;
  cleaningActions: string[];
  timeStart: string | null;
  timeEnd: string | null;
  warnings: string[];
}

export interface DataHealthDiagnostics {
  frequency: string | null;
  validPointCount: number;
  trainPointCount: number;
  testPointCount: number;
  originalRowCount: number;
  droppedRowRate: number;
  invalidTimeRate: number;
  targetMissingRate: number;
  duplicateTimeRate: number;
  missingTimeRate: number;
  outlierRate: number;
  continuityCoverage: number;
  timeContinuous: boolean;
  trainSizeSufficient: boolean;
  testSizeReasonable: boolean;
  timeStart: string | null;
  timeEnd: string | null;
  timeSpanDays: number | null;
}

export interface DataHealth {
  score: number;
  level: "excellent" | "good" | "fair" | "poor";
  warnings: string[];
  suggestions: string[];
  diagnostics: DataHealthDiagnostics;
}

export interface TargetResult {
  targetColumn: string;
  detectedFrequency: string;
  recommendedModelId: string | null;
  rankedModels: RankedModel[];
  backtest: {
    actual: { time: string; value: number }[];
    predictions: Record<string, BacktestPredictionPoint[]>;
  };
  diagnostics: Diagnostics;
  dataHealth: DataHealth;
}

export interface ForecastRunResponse {
  experimentId: string;
  targetColumn: string;
  detectedFrequency: string;
  horizon: number;
  testSize: number;
  recommendedModelId: string | null;
  rankedModels: RankedModel[];
  backtest: {
    actual: { time: string; value: number }[];
    predictions: Record<string, BacktestPredictionPoint[]>;
  };
  diagnostics: Diagnostics;
  dataHealth: DataHealth;
  targetResults: TargetResult[];
  manifest: ExperimentManifest | null;
}

export interface FeatureConfig {
  lagFeatures: boolean;
  rollingFeatures: boolean;
  calendarFeatures: boolean;
  covariates: boolean;
}

export interface ForecastRunRequest {
  runId?: string;
  uploadId: string;
  sheetName: string;
  dataMode: "aggregated" | "raw";
  timeColumn: string;
  targetColumns: string[];
  covariateColumns: string[];
  aggregation: {
    enabled: boolean;
    method: "sum" | "mean" | "count" | "max" | "min";
  };
  frequency: string;
  horizon: number;
  testSize: number;
  selectedModels: string[];
  modelParameters: Record<string, Record<string, number | string | boolean>>;
  featureConfig: FeatureConfig;
  missingValueStrategy: "drop" | "zero" | "ffill" | "interpolate";
  fillMissingTimeSteps: boolean;
  duplicateTimeStrategy: "mean" | "sum" | "first" | "last";
  outlierStrategy: "none" | "clip_iqr";
  outlierIqrMultiplier: number;
  trimStrings: boolean;
  runProfile: "fast" | "balanced" | "accurate";
  parameterStrategy: "default" | "auto";
  randomSeed: number;
  experimentName?: string;
}

export interface RuntimeEstimateRequest {
  rowCount: number;
  frequency: string;
  totalColumnCount: number;
  targetCount: number;
  covariateCount: number;
  featureConfig: FeatureConfig;
  runProfile: "fast" | "balanced" | "accurate";
  parameterStrategy: "default" | "auto";
  device: string;
  selectedModels: string[];
}

export interface RuntimeEstimateItem {
  id: string;
  name: string;
  estimatedSeconds: number;
  confidence: "low" | "medium" | "high";
  reason: string;
  sampleCount: number;
  computeTarget: "cpu" | "gpu";
}

export interface RuntimeEstimateResponse {
  models: RuntimeEstimateItem[];
}

export interface FinalForecastResponse {
  experimentId: string;
  finalModelId: string;
  history: { time: string; value: number }[];
  forecast: { time: string; predicted: number; lower: number | null; upper: number | null }[];
  modelInfo: {
    name: string;
    supportsPredictionInterval: boolean;
  };
}

export type ForecastProgressStatus = "running" | "completed" | "failed";
export type ModelProgressStatus = "queued" | "tuning" | "fitting" | "predicting" | "scoring" | "success" | "failed";

export interface ModelProgress {
  modelId: string;
  modelName: string;
  targetColumn: string;
  status: ModelProgressStatus;
  percent: number;
  message: string;
  fitSeconds: number | null;
  predictSeconds: number | null;
  error: string | null;
}

export interface ForecastProgress {
  runId: string;
  kind: "backtest" | "final";
  status: ForecastProgressStatus;
  phase: string;
  overallPercent: number;
  message: string;
  currentTarget: string | null;
  completedModels: number;
  totalModels: number;
  models: ModelProgress[];
  startedAt: string;
  updatedAt: string;
  error: string | null;
  version: number;
}

export type RuntimeStageId =
  | "pending"
  | "loading"
  | "cleaning"
  | "feature_engineering"
  | "feature_selection"
  | "auto_tuning"
  | "training"
  | "forecast"
  | "residual_analysis"
  | "finished"
  | "failed";

export type RuntimeStepStatus = "pending" | "running" | "completed" | "failed";

export interface RuntimeStateStep {
  id: RuntimeStageId;
  label: string;
  status: RuntimeStepStatus;
  startedAt: string | null;
  finishedAt: string | null;
  elapsedSeconds: number | null;
}

export interface RuntimeResourceSnapshot {
  device: string;
  memoryTotalMb: number | null;
  memoryAvailableMb: number | null;
  memoryUsedMb: number | null;
  cpuPercent: number | null;
  threadCount: number | null;
  gpuLabel: string | null;
}

export interface RuntimeLogEntry {
  id: string;
  timestamp: string;
  stage: RuntimeStageId;
  level: "info" | "warn" | "error" | "success";
  message: string;
  modelId: string | null;
  modelName: string | null;
  targetColumn: string | null;
  metricLabel: string | null;
  metricValue: number | null;
  params: Record<string, number | string | boolean | null>;
}

export interface RuntimeTimelineEntry {
  id: string;
  timestamp: string;
  stage: RuntimeStageId;
  label: string;
  status: RuntimeStepStatus;
  message: string | null;
  modelId: string | null;
  modelName: string | null;
  targetColumn: string | null;
  overallPercent: number | null;
}

export interface RuntimeFeatureFamily {
  id: "target" | "lag" | "rolling" | "calendar" | "holiday" | "covariates";
  label: string;
  enabled: boolean;
  generatedCount: number;
  selectedCount: number;
  importantCount: number;
}

export interface RuntimeFeatureNode {
  id: string;
  name: string;
  source: string;
  formula: string;
  family: string;
  lifecycle: "generated" | "selected" | "dropped" | "used" | "important";
  selected: boolean;
  important: boolean;
  importance: number | null;
  shap: number | null;
  modelIds: string[];
  featureType: "generated" | "known_future_covariate" | "static_covariate";
  generator: string;
  machineId: string | null;
  machineLabel: string | null;
  forecastStrategy: "generated" | "calendar" | "repeat_last_known" | "use_test_timeline";
  backtestStrategy: "generated" | "calendar" | "repeat_last_known" | "use_test_timeline";
  usedDuring: Array<"training" | "backtest" | "forecast">;
  droppedReason: string | null;
  lifecycleTrail: string[];
}

export interface RuntimeFeatureFactorySummary {
  rawColumnCount: number;
  generatedFeatureCount: number;
  userCovariateCount: number;
  selectedFeatureCount: number;
  droppedFeatureCount: number;
  importantFeatureCount: number;
  shapSupportedFeatureCount: number;
}

export interface RuntimeFeatureMachine {
  id: string;
  label: string;
  kind: "generator" | "loader";
  enabled: boolean;
  status: RuntimeStepStatus;
  inputColumns: string[];
  generatedFeatures: string[];
  summary: string;
  durationSeconds: number | null;
  warnings: string[];
}

export interface RuntimeCovariateDescriptor {
  name: string;
  type: "known_future" | "static";
  generator: string;
  forecastStrategy: "calendar" | "repeat_last_known";
  backtestStrategy: "use_test_timeline" | "repeat_last_known";
  usedDuring: Array<"training" | "backtest" | "forecast">;
  note: string | null;
}

export interface RuntimeFeatureSelectionItem {
  name: string;
  status: "selected" | "dropped";
  reason: string | null;
}

export interface RuntimeFeatureSelectionSummary {
  generatedCount: number;
  selectedCount: number;
  droppedCount: number;
  items: RuntimeFeatureSelectionItem[];
}

export interface RuntimeFeaturePipelineStep {
  id: RuntimeStageId;
  label: string;
  status: RuntimeStepStatus;
  inputSummary: string;
  outputSummary: string;
  elapsedSeconds: number | null;
  warnings: string[];
}

export interface RuntimeFeaturePipelineTarget {
  targetColumn: string;
  detectedFrequency: string | null;
  warnings: string[];
  families: RuntimeFeatureFamily[];
  steps: RuntimeFeaturePipelineStep[];
  lineage: RuntimeFeatureNode[];
  summary: RuntimeFeatureFactorySummary | null;
  machines: RuntimeFeatureMachine[];
  covariates: RuntimeCovariateDescriptor[];
  selection: RuntimeFeatureSelectionSummary | null;
}

export interface RuntimeOptimizationTrial {
  trialNumber: number;
  params: Record<string, number | string | boolean | null>;
  status: "running" | "success" | "failed" | "pruned";
  metric: number | null;
  metricLabel: string;
  elapsedSeconds: number;
  selected: boolean;
  message: string | null;
}

export interface RuntimeOptimizationState {
  modelId: string;
  modelName: string;
  targetColumn: string;
  enabled: boolean;
  strategyLabel: string;
  sampler: string | null;
  pruner: string | null;
  currentTrial: number;
  totalTrials: number;
  bestMetric: number | null;
  currentMetric: number | null;
  metricLabel: string;
  selectedParams: Record<string, number | string | boolean | null>;
  status: "idle" | "running" | "completed" | "failed";
  lastMessage: string | null;
  trials: RuntimeOptimizationTrial[];
  warnings: string[];
}

export interface RuntimeModelConsole {
  modelId: string;
  modelName: string;
  targetColumn: string;
  status: "queued" | "tuning" | "fitting" | "predicting" | "scoring" | "success" | "failed";
  currentStage: RuntimeStageId;
  progressPercent: number;
  message: string;
  elapsedSeconds: number;
  estimatedSeconds: number | null;
  estimatedRemainingSeconds: number | null;
  fitSeconds: number | null;
  predictSeconds: number | null;
  tuningSeconds: number | null;
  computeTarget: "cpu" | "gpu";
  resource: RuntimeResourceSnapshot | null;
  optimization: RuntimeOptimizationState | null;
  error: string | null;
}

export interface RuntimeRunDetail {
  runId: string;
  experimentId: string | null;
  kind: "backtest" | "final";
  status: "running" | "completed" | "failed";
  currentStage: RuntimeStageId;
  currentStageLabel: string;
  overallPercent: number;
  message: string;
  currentTarget: string | null;
  estimatedTotalSeconds: number | null;
  estimatedRemainingSeconds: number | null;
  elapsedSeconds: number;
  startedAt: string;
  updatedAt: string;
  stateMachine: RuntimeStateStep[];
  resources: RuntimeResourceSnapshot | null;
  models: RuntimeModelConsole[];
  logs: RuntimeLogEntry[];
  timeline: RuntimeTimelineEntry[];
  featurePipeline: RuntimeFeaturePipelineTarget[];
  optimization: RuntimeOptimizationState[];
  error: string | null;
}

export interface FeatureFactoryResponse {
  experimentId: string;
  targets: RuntimeFeaturePipelineTarget[];
}

export interface ExperimentListItem {
  experimentId: string;
  experimentName: string;
  fileName: string;
  sheetName: string;
  targetColumn: string;
  modelCount: number;
  recommendedModelId: string | null;
  bestMae: number | null;
  createdAt: string;
}

export interface ExperimentDetail extends ExperimentListItem {
  config: Record<string, unknown>;
  dataProfile: Record<string, unknown>;
  rankedModels: RankedModel[];
  backtest: ForecastRunResponse["backtest"];
  diagnostics: Diagnostics;
  dataHealth: DataHealth | null;
  series: { time: string; value: number }[];
  finalForecast: FinalForecastResponse | null;
  modelLogs: unknown[];
  runtime: RuntimeRunDetail | null;
  manifest: ExperimentManifest | null;
  configHash: string | null;
  sourceFileSha256: string | null;
  appVersion: string | null;
  gitCommit: string | null;
  reports: ReportResponse[];
}

export interface ExperimentManifest {
  schemaVersion: "0.3";
  experimentId: string;
  experimentName: string;
  createdAt: string | null;
  configHash: string;
  sourceFileSha256: string;
  environment: {
    appVersion: string;
    gitCommit: string | null;
    pythonVersion: string;
    platform: string;
    device: string;
    memoryTotalMb: number | null;
    memoryAvailableMb: number | null;
    modelCapabilityVersions: Record<string, unknown> | null;
  };
  data: {
    fileName: string;
    fileSize: number;
    fileSha256: string;
    sheetName: string;
    columns: string[];
    timeColumn: string;
    targetColumns: string[];
    covariateColumns: string[];
  };
  configuration: Record<string, unknown>;
  targets: Array<{
    targetColumn: string;
    detectedFrequency: string;
    timeStart: string | null;
    timeEnd: string | null;
    trainStart: string | null;
    trainEnd: string | null;
    testStart: string | null;
    testEnd: string | null;
    recommendedModelId: string | null;
    models: Array<{
      modelId: string;
      modelName: string;
      status: "success" | "failed";
      metrics: Record<string, unknown> | null;
      runtime: Record<string, unknown>;
      warnings: string[];
      error: string | null;
      tuning: Record<string, unknown> | null;
    }>;
  }>;
}

export interface ExperimentRerunResponse {
  experimentId: string;
  configHash: string;
  sourceFileSha256: string;
  manifest: ExperimentManifest;
  runRequestTemplate: Record<string, unknown>;
  fileMatch: {
    uploadId: string | null;
    uploadedFileName: string | null;
    uploadedFileSha256: string | null;
    fileNameMatches: boolean | null;
    sha256Matches: boolean | null;
    exactMatch: boolean | null;
    warnings: string[];
  };
}

export interface DeepSeekSettings {
  apiKey: string;
  baseUrl: string;
  model: string;
  rememberLocal: boolean;
}

export interface DeepSeekConnectionResponse {
  success: boolean;
  model: string;
  message: string;
  code: string | null;
}

export interface LocalRebuildResponse {
  accepted: boolean;
  message: string;
  scriptPath: string;
  logPath: string | null;
}

export interface ReportOptions {
  language: string;
  style: "business" | "technical";
  length: "short" | "medium" | "long";
  includeFeaturePipeline: boolean;
  includeWorkflowReport: boolean;
  includeModelRecommendation: boolean;
  includeModelComparison: boolean;
  includeResidualAnalysis: boolean;
  includeFinalForecast: boolean;
  includeWarnings: boolean;
}

export interface ReportResponse {
  reportId: string;
  experimentId: string;
  contentMarkdown: string;
  createdAt: string;
  model: string;
}

export interface ReportPdfArtifact {
  id: string;
  title: string;
  caption: string;
  dataUrl: string;
  summary: string[];
}
