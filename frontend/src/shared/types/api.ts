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
      status: "success" | "failed";
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
