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
}

export interface BacktestPredictionPoint {
  time: string;
  predicted: number;
  actual: number;
  residual: number;
  absoluteError: number;
  squaredError: number;
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
  diagnostics: {
    originalRowCount: number;
    validRowCount: number;
    droppedRowCount: number;
    duplicateTimeCount: number;
    missingTimeCount: number;
    timeStart: string | null;
    timeEnd: string | null;
    warnings: string[];
  };
  targetResults: unknown[];
}

export interface ForecastRunRequest {
  uploadId: string;
  sheetName: string;
  dataMode: "aggregated" | "raw";
  timeColumn: string;
  targetColumns: string[];
  aggregation: {
    enabled: boolean;
    method: "sum" | "mean" | "count" | "max" | "min";
  };
  frequency: string;
  horizon: number;
  testSize: number;
  selectedModels: string[];
  missingValueStrategy: "drop" | "zero" | "ffill";
  fillMissingTimeSteps: boolean;
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
  diagnostics: ForecastRunResponse["diagnostics"];
  series: { time: string; value: number }[];
  finalForecast: FinalForecastResponse | null;
  modelLogs: unknown[];
  reports: ReportResponse[];
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

export interface ReportOptions {
  language: string;
  style: "business" | "technical";
  length: "short" | "medium" | "long";
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
