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
  workspaceId: string | null;
  fileName: string;
  fileSize: number;
  fileSha256: string;
  sheets: SheetPreview[];
}

export interface AuthUser {
  userId: string;
  username: string;
  displayName: string;
  isAdmin: boolean;
  isActive: boolean;
  createdAt: string;
}

export interface WorkspaceSummary {
  workspaceId: string;
  name: string;
  kind: "personal" | "shared" | "example";
  role: "owner" | "member";
  isReadOnly: boolean;
  ownerUserId: string;
  isPersonal: boolean;
  isOwner: boolean;
  createdAt: string;
}

export interface AuthSessionResponse {
  authenticated: boolean;
  bootstrapRequired: boolean;
  user: AuthUser | null;
  workspaces: WorkspaceSummary[];
  defaultWorkspaceId: string | null;
}

export interface UsernameAvailabilityResponse {
  available: boolean;
  normalizedUsername: string;
  reason: "available" | "taken" | "invalid";
  message: string | null;
}

export interface BootstrapRequest {
  username: string;
  displayName: string;
  password: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  displayName: string;
  password: string;
}

export interface CreateUserRequest {
  username: string;
  displayName: string;
  password: string;
  isAdmin: boolean;
}

export interface UpdateUserRequest {
  displayName?: string;
  isActive?: boolean;
}

export interface UpdateUserPasswordRequest {
  password: string;
}

export interface UserGroupRef {
  groupId: string;
  name: string;
}

export interface UserSummary {
  userId: string;
  username: string;
  displayName: string;
  isAdmin: boolean;
  isActive: boolean;
  createdAt: string;
  groups: UserGroupRef[];
}

export interface UserGroupSummary {
  groupId: string;
  name: string;
  description: string | null;
  memberCount: number;
  createdAt: string;
}

export interface CreateUserGroupRequest {
  name: string;
  description?: string;
}

export interface UpdateUserGroupsRequest {
  groupIds: string[];
}

export interface CreateWorkspaceRequest {
  name: string;
}

export interface UpdateWorkspaceRequest {
  name: string;
}

export interface WorkspaceMemberResponse {
  userId: string;
  username: string;
  displayName: string;
  role: "owner" | "member";
  isActive: boolean;
  createdAt: string;
}

export interface AddWorkspaceMemberRequest {
  userId: string;
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
  accelerator: {
    hardwareDetected: boolean;
    runtimeAvailable: boolean;
    type: "nvidia" | "mps" | null;
    name: string | null;
    memoryTotalMb: number | null;
    driverVersion: string | null;
    frameworkVersion: string | null;
    frameworkBuild: string | null;
    cudaRuntime: string | null;
    reason: string | null;
  };
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
  holidayFeatures: boolean;
  covariates: boolean;
}

export type MissingValueStrategy = "drop" | "zero" | "ffill" | "bfill" | "interpolate" | "time" | "median";
export type OutlierStrategy = "none" | "clip_iqr" | "hampel";

export interface CleaningConfig {
  preset: "conservative" | "standard" | "strict" | "custom";
  sortByTime: boolean;
  invalidTimeStrategy: "drop" | "error";
  trimStrings: boolean;
  normalizeThousandsSeparators: boolean;
  missingValueStrategy: MissingValueStrategy;
  interpolationLimit: number | null;
  fillMissingTimeSteps: boolean;
  duplicateTimeStrategy: "mean" | "sum" | "first" | "last";
  outlierStrategy: OutlierStrategy;
  outlierIqrMultiplier: number;
  hampelWindow: number;
  hampelSigma: number;
}

export interface HolidayConfig {
  enabled: boolean;
  countryCode: string;
  subdivision: string | null;
  observed: boolean;
  windowDays: number;
}

export interface CovariateConfig {
  column: string;
  type: "known_future" | "static";
  backtestStrategy: "repeat_last_known" | "historical_mean" | "use_test_values";
  missingValueStrategy: MissingValueStrategy;
}

export interface HolidayCalendarCatalog {
  defaultCountryCode: string;
  countries: Array<{ code: string; name: string; subdivisions: string[] }>;
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
  cleaningConfig: CleaningConfig;
  covariateConfigs: CovariateConfig[];
  holidayConfig: HolidayConfig;
  missingValueStrategy: MissingValueStrategy;
  fillMissingTimeSteps: boolean;
  duplicateTimeStrategy: "mean" | "sum" | "first" | "last";
  outlierStrategy: OutlierStrategy;
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
  unknownFutureForecastCount: number;
  perPrimaryModelCovariateCount: number;
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
export type FeatureStepStatus = RuntimeStepStatus | "skipped";

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
  level: "info" | "warn" | "error" | "success";
  message: string | null;
  modelId: string | null;
  modelName: string | null;
  targetColumn: string | null;
  overallPercent: number | null;
}

export interface RuntimeEvent {
  schemaVersion: "0.4";
  id: string;
  sequence: number;
  runId: string;
  timestamp: string;
  eventType: "stage" | "model" | "resource" | "feature" | "optimization" | "log" | "terminal";
  stage: RuntimeStageId;
  status: RuntimeStepStatus;
  message: string;
  modelId: string | null;
  targetColumn: string | null;
  progressPercent: number | null;
  metricLabel: string | null;
  metricValue: number | null;
  payload: Record<string, unknown>;
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
  forecastStrategy: "generated" | "calendar" | "use_future_rows" | "repeat_last_known";
  backtestStrategy: "generated" | "calendar" | "use_future_rows" | "repeat_last_known" | "historical_mean" | "use_test_timeline" | "use_test_values";
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
  status: FeatureStepStatus;
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
  forecastStrategy: "calendar" | "use_future_rows" | "repeat_last_known";
  backtestStrategy: "use_test_timeline" | "repeat_last_known" | "historical_mean" | "use_test_values";
  usedDuring: Array<"training" | "backtest" | "forecast">;
  leakageRisk: boolean;
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

export interface RuntimeFeatureColumnProfile {
  name: string;
  dtype: string;
  nonNullCount: number;
  nullCount: number;
  minimum: number | null;
  maximum: number | null;
  mean: number | null;
  std: number | null;
}

export interface RuntimeFeatureDataProfile {
  rowCount: number;
  columnCount: number;
  columns: string[];
  missingValueCount: number;
  invalidValueCount: number;
  memoryBytes: number;
  columnProfiles: RuntimeFeatureColumnProfile[];
}

export interface RuntimeFeatureVisualization {
  kind: string;
  timeStart: string | null;
  timeEnd: string | null;
  markers: Array<{ time: string; label: string; kind: string }>;
  sampleValues: number[];
  sampleLabels: string[];
  windowSize: number | null;
}

export interface RuntimeFeaturePipelineStep {
  id: string;
  sequence: number;
  label: string;
  description: string;
  machineId: string | null;
  status: FeatureStepStatus;
  progressPercent: number;
  startedAt: string | null;
  finishedAt: string | null;
  inputSummary: string;
  outputSummary: string;
  inputProfile: RuntimeFeatureDataProfile | null;
  outputProfile: RuntimeFeatureDataProfile | null;
  generatedFeatures: string[];
  selectedFeatures: string[];
  droppedFeatures: string[];
  skipReason: string | null;
  error: string | null;
  elapsedSeconds: number | null;
  warnings: string[];
  visualization: RuntimeFeatureVisualization | null;
}

export interface RuntimeFeaturePipelineTarget {
  schemaVersion: "0.4";
  targetColumn: string;
  detectedFrequency: string | null;
  status: FeatureStepStatus;
  progressPercent: number;
  currentStepId: string | null;
  traceMode: "live" | "reconstructed" | "legacy_inferred";
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
  metricLabel: string | null;
  currentMetric: number | null;
  bestMetric: number | null;
  selectedParams: Record<string, number | string | boolean | null>;
  warnings: string[];
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
  events: RuntimeEvent[];
  featurePipeline: RuntimeFeaturePipelineTarget[];
  optimization: RuntimeOptimizationState[];
  error: string | null;
}

export interface RuntimeEventsResponse {
  runId: string;
  events: RuntimeEvent[];
}

export interface FeatureFactoryResponse {
  experimentId: string;
  targets: RuntimeFeaturePipelineTarget[];
}

export interface ExplainabilityFeatureItem {
  feature: string;
  importance: number | null;
  rank: number | null;
  meanAbsShap: number | null;
  direction: "positive" | "negative" | "mixed" | "neutral" | null;
}

export interface ExplainabilitySinglePointContribution {
  feature: string;
  value: number | null;
  shapValue: number | null;
  direction: "positive" | "negative" | "neutral";
}

export interface ExplainabilitySinglePoint {
  time: string | null;
  actual: number | null;
  predicted: number | null;
  residual: number | null;
  absoluteError: number | null;
  contributions: ExplainabilitySinglePointContribution[];
  warnings: string[];
}

export interface ExplainabilityModelSummary {
  modelId: string;
  modelName: string;
  targetColumn: string;
  supported: boolean;
  warning: string | null;
  featureImportance: ExplainabilityFeatureItem[];
  shapSupported: boolean;
  shapWarning: string | null;
  shapTopFeatures: ExplainabilityFeatureItem[];
  singlePoint: ExplainabilitySinglePoint | null;
}

export interface ExperimentExplainabilityResponse {
  experimentId: string;
  recommendedModelId: string | null;
  models: ExplainabilityModelSummary[];
}

export interface WorkbenchIdeaAnalyzeRequest {
  idea: string;
  context: {
    targetColumn?: string | null;
    frequency?: string | null;
    availableColumns?: string[];
    horizon?: number | null;
    domain?: string | null;
  };
  mode?: "offline" | "online" | "dual";
}

export interface WorkbenchDataSourceCandidate {
  id: string;
  name: string;
  category: "built_in" | "user_upload" | "external_registry" | "connector_placeholder";
  description: string;
  frequencySupport: string[];
  futureAvailability: "known_future" | "static" | "unknown_future" | "not_applicable";
  implementationStatus: "available" | "placeholder" | "unsupported";
  warnings: string[];
}

export interface WorkbenchCovariatePlan {
  suggestedColumns: string[];
  covariateType: "known_future" | "static" | "unknown_future" | "mixed" | "none";
  backtestPolicy: string;
  forecastPolicy: string;
  leakagePolicy: string;
}

export interface WorkbenchIdeaAnalyzeResponse {
  route: "feature_engineering_data" | "custom_model" | "hybrid" | "clarify" | "unsupported";
  confidence: number;
  rationale: string;
  requiredInputs: string[];
  candidateDataSources: WorkbenchDataSourceCandidate[];
  covariatePlan: WorkbenchCovariatePlan | null;
  leakageWarnings: string[];
  nextApiCalls: string[];
}

export type AgentSkillCategory = "read" | "analysis" | "action";
export type AgentRunStatus = "planned" | "running" | "completed" | "failed" | "cancelled";
export type AgentPlanStepStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "skipped";
export type AgentArtifactKind = "summary" | "markdown" | "chart" | "diagnosis" | "report" | "table" | "warning" | "run_request";
export type AgentEventType = "status" | "plan" | "skill" | "artifact" | "message" | "warning" | "error";

export interface AgentSkillDefinition {
  skillId: string;
  category: AgentSkillCategory;
  requiredInputs: string[];
  sideEffects: string[];
  costLevel: "low" | "medium" | "high";
  expectedDuration: string;
  workspaceScope: "experiment" | "workspace";
  supportsStreaming: boolean;
  producesArtifacts: boolean;
  description: string;
}

export interface AgentPlanStep {
  stepId: string;
  title: string;
  detail: string;
  skillId: string;
  status: AgentPlanStepStatus;
  reads: string[];
  runsModel: boolean;
  generatesChart: boolean;
  writesReport: boolean;
  estimatedDuration: string | null;
  risks: string[];
}

export interface AgentSkillInvocation {
  invocationId: string;
  skillId: string;
  status: AgentPlanStepStatus;
  startedAt: string | null;
  finishedAt: string | null;
  inputSummary: string;
  outputSummary: string;
  warning: string | null;
  error: string | null;
}

export interface AgentArtifact {
  artifactId: string;
  kind: AgentArtifactKind;
  title: string;
  summary: string;
  createdAt: string;
  sourceSkillId: string | null;
  payload: Record<string, unknown>;
  linksToReport: boolean;
}

export interface AgentContextSnapshot {
  experimentId: string;
  experimentName: string;
  workspaceId: string;
  workspaceName: string | null;
  targetColumn: string | null;
  recommendedModelId: string | null;
  currentPage: string | null;
  currentTab: string | null;
  selectedModelId: string | null;
  selectedFeatureId: string | null;
  selectedArtifactId: string | null;
  selectedVisualId: string | null;
  selectedAnomalyTime: string | null;
  availableColumns: string[];
  covariates: RuntimeCovariateDescriptor[];
  warnings: string[];
  availableReports: Array<{ reportId: string; title: string }>;
}

export interface AgentMessage {
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
}

export interface AgentRunEvent {
  eventId: string;
  type: AgentEventType;
  title: string;
  detail: string;
  timestamp: string;
  stepId: string | null;
  skillId: string | null;
  artifactId: string | null;
  status: string | null;
}

export interface AgentRunRequest {
  prompt: string;
  currentPage?: string | null;
  currentTab?: string | null;
  selectedModelId?: string | null;
  selectedFeatureId?: string | null;
  selectedArtifactId?: string | null;
  selectedVisualId?: string | null;
  selectedAnomalyTime?: string | null;
  autoExecute?: boolean;
}

export interface AgentRunResponse {
  runId: string;
  experimentId: string;
  status: AgentRunStatus;
  plan: AgentPlanStep[];
  currentMessage: string | null;
  availableSkills: AgentSkillDefinition[];
}

export interface AgentHistoryItem {
  runId: string;
  requestPreview: string;
  status: AgentRunStatus;
  createdAt: string;
  updatedAt: string;
  artifactCount: number;
  skillIds: string[];
  lastAssistantMessage: string | null;
}

export interface AgentRunDetail {
  runId: string;
  experimentId: string;
  workspaceId: string;
  createdByUserId: string;
  status: AgentRunStatus;
  request: AgentRunRequest;
  context: AgentContextSnapshot;
  plan: AgentPlanStep[];
  events: AgentRunEvent[];
  messages: AgentMessage[];
  skillInvocations: AgentSkillInvocation[];
  artifacts: AgentArtifact[];
  availableSkills: AgentSkillDefinition[];
  estimatedDuration: string | null;
  risks: string[];
  summary: string | null;
  canCancel: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AgentRunEventsResponse {
  runId: string;
  events: AgentRunEvent[];
}

export interface AttributionSnapshotSection {
  title: string;
  summary: string[];
  highlights: Array<Record<string, unknown>>;
  askAgentPrompts: string[];
}

export interface AttributionSnapshot {
  experimentId: string;
  updatedAt: string | null;
  overview: AttributionSnapshotSection;
  quickDiagnosis: AttributionSnapshotSection;
  anomalyResidualLab: AttributionSnapshotSection;
  deepAttribution: AttributionSnapshotSection;
  scenarioExecutiveOutput: AttributionSnapshotSection;
  warnings: string[];
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
  workspaceId: string | null;
  workspaceName: string | null;
  createdByUserId: string | null;
  createdByUsername: string | null;
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
  explainability: ExperimentExplainabilityResponse | null;
  runtime: RuntimeRunDetail | null;
  attribution: AttributionSnapshot | null;
  manifest: ExperimentManifest | null;
  configHash: string | null;
  sourceFileSha256: string | null;
  appVersion: string | null;
  gitCommit: string | null;
  reports: ReportResponse[];
  agentHistorySummary: AgentHistoryItem[];
  availableAgentSkills: AgentSkillDefinition[];
}

export interface ExperimentManifest {
  schemaVersion: "0.3" | "0.4";
  experimentId: string;
  experimentName: string;
  createdAt: string | null;
  configHash: string;
  sourceFileSha256: string;
  datasetHash: string | null;
  featurePipelineVersion: string | null;
  runtimeEventSchemaVersion: string | null;
  randomSeed: number | null;
  environment: {
    appVersion: string;
    gitCommit: string | null;
    pythonVersion: string;
    platform: string;
    device: string;
    memoryTotalMb: number | null;
    memoryAvailableMb: number | null;
    modelCapabilityVersions: Record<string, unknown> | null;
    packageVersions: Record<string, string>;
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
  featurePipelines: RuntimeFeaturePipelineTarget[];
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
  workspaceId: string | null;
  workspaceName: string | null;
  createdByUserId: string | null;
  createdByUsername: string | null;
}

export interface ReportPdfArtifact {
  id: string;
  title: string;
  caption: string;
  dataUrl: string;
  summary: string[];
}

export type FeedbackKind = "urgent" | "feedback" | "ramble";
export type FeedbackStatus = "open" | "in_progress" | "done" | "ignored";
export type FeedbackNotifyStatus = "pending" | "sent" | "failed" | "skipped";

export interface FeedbackCreateRequest {
  kind: FeedbackKind;
  title?: string | null;
  content: string;
  sourcePage?: string | null;
}

export interface FeedbackItem {
  feedbackId: string;
  kind: FeedbackKind;
  title: string | null;
  content: string;
  sourcePage: string | null;
  status: FeedbackStatus;
  notifyStatus: FeedbackNotifyStatus;
  notifyError: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface FeedbackListResponse {
  items: FeedbackItem[];
}

export interface FeedbackNotifyTestResponse {
  success: boolean;
  notifyStatus: FeedbackNotifyStatus;
  message: string;
  error: string | null;
}
