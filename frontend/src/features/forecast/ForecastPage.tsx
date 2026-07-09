import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Link } from "react-router-dom";
import { createRunId, fetchDeviceInfo, fetchHolidayCalendars, fetchModels, fetchRuntimeDetail, fetchRuntimeEstimate, runFinalForecast, runForecast, subscribeForecastProgress, subscribeRuntimeEvents } from "../../shared/api/client";
import { DataTable } from "../../shared/components/Table";
import { EmptyState, ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, Stepper, surface, Tabs } from "../../shared/components/Ui";
import { zhCN } from "../../shared/i18n/zhCN";
import type { CleaningConfig, CovariateConfig, DeviceInfo, FeatureConfig, ForecastProgress, ForecastRunRequest, ForecastRunResponse, HolidayCalendarCatalog, HolidayConfig, ModelCapability, RuntimeEstimateItem, RuntimeRunDetail, SheetPreview, UploadPreviewResponse } from "../../shared/types/api";
import { useLabStore } from "../../app/store";
import {
  AbsoluteErrorTimelineChart,
  ActualVsPredictedChart,
  defaultVisibleModelIds,
  FinalForecastChart,
  MetricBarChart,
  NormalizedMetricChart,
  PredictedResidualScatterChart,
  ResidualDistributionChart,
  ResidualTimelineChart
} from "../visualization/Charts";
import { ReportPanel } from "../reports/ReportPanel";
import { DataHealthPanel } from "./DataHealthPanel";
import { getParameterHelp } from "./parameterHelp";
import { ReproducibilityPanel } from "./ReproducibilityPanel";
import { ModelLeaderboard } from "./ModelLeaderboard";
import { ExplainabilityPanel } from "../runtime/ExplainabilityPanel";
import { FeatureFactoryPanel } from "../runtime/FeatureFactoryPanel";
import { RuntimeModelConsoleDrawer } from "../runtime/RuntimeModelConsoleDrawer";
import { WorkbenchIdeaPanel } from "./WorkbenchIdeaPanel";

const modelDefaults = ["naive", "seasonal_naive", "moving_average", "arima", "ets", "prophet", "xgboost", "lightgbm", "random_forest"];
const steps = ["选择数据模式", "选择字段", "选择模型", "设置回测", "运行实验"];
const maxTargetColumns = 8;
const maxModelRuns = 32;
const maxHeavyModelRuns = 4;
const heavyModelIds = new Set(["prophet", "timesfm"]);
const selectedModelsStorageKey = "tsfl_forecast_selected_models_v1";
const cleaningPresets: Record<Exclude<CleaningConfig["preset"], "custom">, Partial<CleaningConfig>> = {
  conservative: { missingValueStrategy: "drop", interpolationLimit: null, fillMissingTimeSteps: false, outlierStrategy: "none" },
  standard: { missingValueStrategy: "time", interpolationLimit: 3, fillMissingTimeSteps: true, outlierStrategy: "none" },
  strict: { missingValueStrategy: "time", interpolationLimit: 7, fillMissingTimeSteps: true, outlierStrategy: "hampel" }
};

const defaultHolidayConfig: HolidayConfig = { enabled: true, countryCode: "CN", subdivision: null, observed: true, windowDays: 1 };

const defaultFeatureConfig: FeatureConfig = {
  lagFeatures: true,
  rollingFeatures: true,
  calendarFeatures: true,
  holidayFeatures: true,
  covariates: true
};

type ModelParameterValue = number | string | boolean;

interface ModelParameterField {
  key: string;
  label: string;
  type: "number" | "select" | "boolean";
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
}

const seasonalityOptions = [
  { value: "auto", label: "auto" },
  { value: "on", label: "on" },
  { value: "off", label: "off" }
];

const modelParameterDefaults: Record<string, Record<string, ModelParameterValue>> = {
  seasonal_naive: { period: 0 },
  moving_average: { window: 7 },
  arima: { p: 1, d: 1, q: 1 },
  ets: { trend: "auto" },
  prophet: { intervalWidth: 0.8, seasonalityMode: "additive", changepointPriorScale: 0.05, dailySeasonality: "auto", weeklySeasonality: "auto", yearlySeasonality: "auto" },
  timesfm: { maxContext: 512, normalizeInputs: true },
  xgboost: { nEstimators: 200, maxDepth: 3, learningRate: 0.05 },
  lightgbm: { nEstimators: 250, numLeaves: 31, learningRate: 0.05 },
  random_forest: { nEstimators: 120, maxDepth: 18, minSamplesLeaf: 2 }
};

const modelParameterFields: Record<string, ModelParameterField[]> = {
  seasonal_naive: [{ key: "period", label: "季节周期", type: "number", min: 0, max: 8760, step: 1 }],
  moving_average: [{ key: "window", label: "窗口长度", type: "number", min: 2, max: 720, step: 1 }],
  arima: [
    { key: "p", label: "AR 阶 p", type: "number", min: 0, max: 5, step: 1 },
    { key: "d", label: "差分 d", type: "number", min: 0, max: 2, step: 1 },
    { key: "q", label: "MA 阶 q", type: "number", min: 0, max: 5, step: 1 }
  ],
  ets: [{ key: "trend", label: "趋势项", type: "select", options: [{ value: "auto", label: "auto" }, { value: "none", label: "none" }, { value: "add", label: "add" }] }],
  prophet: [
    { key: "intervalWidth", label: "区间宽度", type: "number", min: 0.5, max: 0.99, step: 0.01 },
    { key: "seasonalityMode", label: "季节性模式", type: "select", options: [{ value: "additive", label: "additive" }, { value: "multiplicative", label: "multiplicative" }] },
    { key: "changepointPriorScale", label: "趋势拐点灵活度", type: "number", min: 0.001, max: 1, step: 0.001 },
    { key: "dailySeasonality", label: "日季节性", type: "select", options: seasonalityOptions },
    { key: "weeklySeasonality", label: "周季节性", type: "select", options: seasonalityOptions },
    { key: "yearlySeasonality", label: "年季节性", type: "select", options: seasonalityOptions }
  ],
  timesfm: [
    { key: "maxContext", label: "上下文长度", type: "number", min: 32, max: 512, step: 32 },
    { key: "normalizeInputs", label: "归一化输入", type: "boolean" }
  ],
  xgboost: [
    { key: "nEstimators", label: "树数量", type: "number", min: 20, max: 500, step: 10 },
    { key: "maxDepth", label: "最大深度", type: "number", min: 1, max: 10, step: 1 },
    { key: "learningRate", label: "学习率", type: "number", min: 0.01, max: 0.5, step: 0.01 }
  ],
  lightgbm: [
    { key: "nEstimators", label: "树数量", type: "number", min: 20, max: 600, step: 10 },
    { key: "numLeaves", label: "叶子数", type: "number", min: 7, max: 255, step: 1 },
    { key: "learningRate", label: "学习率", type: "number", min: 0.01, max: 0.5, step: 0.01 }
  ],
  random_forest: [
    { key: "nEstimators", label: "树数量", type: "number", min: 20, max: 300, step: 10 },
    { key: "maxDepth", label: "最大深度", type: "number", min: 2, max: 40, step: 1 },
    { key: "minSamplesLeaf", label: "叶节点最少样本", type: "number", min: 1, max: 20, step: 1 }
  ]
};

type ResultTab = "dataHealth" | "overview" | "residual" | "metrics" | "distribution" | "featureFactory" | "explainability" | "final" | "reproducibility" | "report";

function isRunnableModel(model: ModelCapability) {
  return model.enabledInMvp && model.installStatus === "available";
}

function modelStatusText(model: ModelCapability) {
  if (model.installStatus === "planned") return "计划中";
  if (model.installStatus === "not_installed") return "未安装";
  if (model.installStatus === "downloading") return "需要下载";
  if (model.installStatus === "failed") return "不可用";
  return "可运行";
}

function modelStatusTone(model: ModelCapability): "neutral" | "good" | "warn" | "bad" | "info" {
  if (model.installStatus === "available") return "good";
  if (model.installStatus === "downloading") return "warn";
  if (model.installStatus === "planned") return "neutral";
  if (model.installStatus === "failed") return "bad";
  return "warn";
}

function metricText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

function dataHealthTone(level: ForecastRunResponse["dataHealth"]["level"]): "good" | "info" | "warn" | "bad" {
  if (level === "excellent") return "good";
  if (level === "good") return "info";
  if (level === "fair") return "warn";
  return "bad";
}

function dataHealthLevelText(level: ForecastRunResponse["dataHealth"]["level"]) {
  if (level === "excellent") return "优秀";
  if (level === "good") return "良好";
  if (level === "fair") return "一般";
  return "偏弱";
}

function loadPersistedSelectedModels(): { hasValue: boolean; values: string[] } {
  if (typeof window === "undefined") return { hasValue: false, values: [] };
  try {
    const raw = window.localStorage.getItem(selectedModelsStorageKey);
    if (raw === null) return { hasValue: false, values: [] };
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return { hasValue: false, values: [] };
    return {
      hasValue: true,
      values: parsed.filter((item): item is string => typeof item === "string")
    };
  } catch {
    return { hasValue: false, values: [] };
  }
}

function persistSelectedModels(modelIds: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(selectedModelsStorageKey, JSON.stringify(Array.from(new Set(modelIds))));
  } catch {
    // ignore local storage failures
  }
}

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function runtimeConfidenceTone(confidence: RuntimeEstimateItem["confidence"]): "good" | "info" | "warn" {
  if (confidence === "high") return "good";
  if (confidence === "medium") return "info";
  return "warn";
}

function formatCompactDuration(seconds: number) {
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 10) return `${minutes.toFixed(1)}m`;
  return `${Math.round(minutes)}m`;
}

function covariateDefaults(column: string): CovariateConfig {
  return {
    column,
    type: /weekday|dayofweek|month|quarter|weekend|workday|holiday/i.test(column) ? "known_future" : "static",
    backtestStrategy: "repeat_last_known",
    missingValueStrategy: "ffill"
  };
}

function normalizeCovariateConfig(column: string, value?: Partial<CovariateConfig> | null): CovariateConfig {
  return {
    ...covariateDefaults(column),
    ...(value ?? {}),
    column,
    type: value?.type === "known_future" ? "known_future" : "static",
    backtestStrategy:
      value?.backtestStrategy === "historical_mean"
        ? "historical_mean"
        : value?.backtestStrategy === "use_test_values"
          ? "use_test_values"
          : "repeat_last_known"
  };
}

function leakageReminderStorageKey(userId: string | null | undefined) {
  return `tsfl_covariate_use_test_values_warning:${userId ?? "anonymous"}`;
}

const runtimeStageSequence: Array<{ id: RuntimeRunDetail["currentStage"]; label: string }> = [
  { id: "pending", label: "Pending" },
  { id: "loading", label: "Loading" },
  { id: "cleaning", label: "Cleaning" },
  { id: "feature_engineering", label: "Feature Engineering" },
  { id: "feature_selection", label: "Feature Selection" },
  { id: "auto_tuning", label: "Auto Tuning" },
  { id: "training", label: "Training" },
  { id: "forecast", label: "Forecast" },
  { id: "residual_analysis", label: "Residual Analysis" },
  { id: "finished", label: "Finished" }
];

function runtimeStageIndex(stageId: RuntimeRunDetail["currentStage"]) {
  return runtimeStageSequence.findIndex((stage) => stage.id === stageId);
}

function runtimeStepState(
  currentStage: RuntimeRunDetail["currentStage"],
  targetStage: RuntimeRunDetail["currentStage"],
  modelStatus?: "queued" | "tuning" | "fitting" | "predicting" | "scoring" | "success" | "failed"
) {
  if (modelStatus === "failed") {
    if (targetStage === currentStage) return "failed";
    return runtimeStageIndex(targetStage) < runtimeStageIndex(currentStage) ? "completed" : "pending";
  }
  if (modelStatus === "success" && targetStage === "finished") return "completed";
  if (modelStatus === "success") {
    if (targetStage === currentStage) return "completed";
    return runtimeStageIndex(targetStage) < runtimeStageIndex(currentStage) ? "completed" : "pending";
  }
  if (targetStage === currentStage) return "running";
  return runtimeStageIndex(targetStage) < runtimeStageIndex(currentStage) ? "completed" : "pending";
}

function runtimeStepTone(state: "pending" | "running" | "completed" | "failed") {
  if (state === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200";
  if (state === "running") return "border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200";
  if (state === "failed") return "border-red-200 bg-red-50 text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200";
  return "border-slate-200 bg-slate-50 text-slate-500 dark:border-white/10 dark:bg-[#111827] dark:text-slate-400";
}

function runtimeStepLabel(state: "pending" | "running" | "completed" | "failed") {
  if (state === "completed") return "已完成";
  if (state === "running") return "进行中";
  if (state === "failed") return "失败";
  return "待开始";
}

function runtimeStageCompactLabel(stageId: RuntimeRunDetail["currentStage"]) {
  switch (stageId) {
    case "pending":
      return "排队";
    case "loading":
      return "加载";
    case "cleaning":
      return "清洗";
    case "feature_engineering":
      return "特征工程";
    case "feature_selection":
      return "特征筛选";
    case "auto_tuning":
      return "自动调参";
    case "training":
      return "训练";
    case "forecast":
      return "预测";
    case "residual_analysis":
      return "残差";
    case "finished":
      return "完成";
    default:
      return stageId;
  }
}

type ResourceLevel = "green" | "yellow" | "red" | "gray";

interface ModelResourceAssessment {
  level: ResourceLevel;
  label: string;
  reason: string;
  minRamMb: number;
  dataRamMb: number;
  loadRank: number;
}

const modelResourceProfiles: Record<string, { baseRamMb: number; dataMultiplier: number; loadRank: number }> = {
  naive: { baseRamMb: 128, dataMultiplier: 0.5, loadRank: 1 },
  seasonal_naive: { baseRamMb: 160, dataMultiplier: 0.6, loadRank: 1 },
  moving_average: { baseRamMb: 128, dataMultiplier: 0.5, loadRank: 1 },
  arima: { baseRamMb: 512, dataMultiplier: 1.3, loadRank: 2 },
  ets: { baseRamMb: 512, dataMultiplier: 1.1, loadRank: 2 },
  random_forest: { baseRamMb: 768, dataMultiplier: 2.0, loadRank: 3 },
  xgboost: { baseRamMb: 1024, dataMultiplier: 2.4, loadRank: 3 },
  lightgbm: { baseRamMb: 1024, dataMultiplier: 2.2, loadRank: 3 },
  prophet: { baseRamMb: 1024, dataMultiplier: 1.8, loadRank: 3 },
  nbeats: { baseRamMb: 2048, dataMultiplier: 2.5, loadRank: 4 },
  nhits: { baseRamMb: 2048, dataMultiplier: 2.5, loadRank: 4 },
  patchtst: { baseRamMb: 3072, dataMultiplier: 3.0, loadRank: 4 },
  timesfm: { baseRamMb: 4096, dataMultiplier: 1.4, loadRank: 5 },
  lag_llama: { baseRamMb: 4096, dataMultiplier: 2.0, loadRank: 5 },
  chronos: { baseRamMb: 4096, dataMultiplier: 2.0, loadRank: 5 },
  moirai: { baseRamMb: 4096, dataMultiplier: 2.0, loadRank: 5 }
};

const resourceToneClass: Record<ResourceLevel, string> = {
  green: "bg-emerald-400 shadow-emerald-400/40",
  yellow: "bg-amber-400 shadow-amber-400/40",
  red: "bg-red-500 shadow-red-500/40",
  gray: "bg-slate-400 shadow-slate-400/30"
};

function formatMemory(mb: number | null | undefined) {
  if (mb === null || mb === undefined || Number.isNaN(mb)) return "未知";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

function estimateDataRamMb({
  upload,
  sheet,
  dataMode,
  targetColumns,
  horizon,
  testSize
}: {
  upload: UploadPreviewResponse | null;
  sheet: SheetPreview | null;
  dataMode: "aggregated" | "raw";
  targetColumns: string[];
  horizon: number;
  testSize: number;
}) {
  const fileMb = upload ? upload.fileSize / 1024 / 1024 : 1;
  const rowCount = sheet?.rowCountApprox ?? Math.max(100, Math.round(fileMb * 4000));
  const columnCount = Math.max(sheet?.columns.length ?? 2, 1);
  const inMemoryFrameMb = (rowCount * columnCount * 96) / 1024 / 1024;
  const parseMultiplier = dataMode === "raw" ? 3.8 : 2.4;
  const targetMultiplier = Math.max(targetColumns.length, 1);
  const horizonBufferMb = Math.max(8, (horizon + testSize) * targetMultiplier * 0.45);
  return Math.max(fileMb * parseMultiplier, inMemoryFrameMb * parseMultiplier) + horizonBufferMb + Math.max(0, targetMultiplier - 1) * 128;
}

function assessModelResource({
  model,
  deviceInfo,
  upload,
  sheet,
  dataMode,
  targetColumns,
  horizon,
  testSize
}: {
  model: ModelCapability;
  deviceInfo: DeviceInfo | null;
  upload: UploadPreviewResponse | null;
  sheet: SheetPreview | null;
  dataMode: "aggregated" | "raw";
  targetColumns: string[];
  horizon: number;
  testSize: number;
}): ModelResourceAssessment {
  const profile = modelResourceProfiles[model.id] ?? { baseRamMb: 768, dataMultiplier: 1.4, loadRank: 3 };
  const dataRamMb = estimateDataRamMb({ upload, sheet, dataMode, targetColumns, horizon, testSize });
  const minRamMb = Math.ceil(profile.baseRamMb + dataRamMb * profile.dataMultiplier);
  const totalMb = deviceInfo?.memoryTotalMb ?? null;
  const availableMb = deviceInfo?.memoryAvailableMb ?? null;

  if (!model.enabledInMvp || model.installStatus !== "available") {
    return { level: "gray", label: "无法运行", reason: model.unavailableReason ?? modelStatusText(model), minRamMb, dataRamMb, loadRank: 99 };
  }
  if (totalMb && minRamMb > totalMb * 1.15) {
    return { level: "gray", label: "无法运行", reason: `最小 RAM 超过主机总内存 ${formatMemory(totalMb)}`, minRamMb, dataRamMb, loadRank: 98 };
  }
  if (model.requiresGpu && deviceInfo?.device === "cpu") {
    return { level: "red", label: "高压力", reason: deviceInfo.accelerator.reason ?? "当前运行环境无法使用 GPU", minRamMb, dataRamMb, loadRank: profile.loadRank };
  }
  if (!availableMb) {
    return { level: "yellow", label: "压力未知", reason: "未读取到可用内存，使用保守估算", minRamMb, dataRamMb, loadRank: profile.loadRank };
  }
  if (minRamMb <= availableMb * 0.55) {
    return { level: "green", label: "无压力", reason: `预计占用低于可用内存 ${formatMemory(availableMb)} 的 55%`, minRamMb, dataRamMb, loadRank: profile.loadRank };
  }
  if (minRamMb <= availableMb * 0.85) {
    return { level: "yellow", label: "有压力", reason: `接近可用内存 ${formatMemory(availableMb)}`, minRamMb, dataRamMb, loadRank: profile.loadRank };
  }
  return { level: "red", label: "高压力", reason: `可能挤占可用内存 ${formatMemory(availableMb)}`, minRamMb, dataRamMb, loadRank: profile.loadRank };
}

function RunningProgress({
  finalForecastMode = false,
  selectedModelIds = [],
  models = [],
  finalModelId = "",
  elapsedSeconds = 0,
  parameterStrategy = "default",
  progress,
  runtimeDetail = null
}: {
  finalForecastMode?: boolean;
  selectedModelIds?: string[];
  models?: ModelCapability[];
  finalModelId?: string;
  elapsedSeconds?: number;
  parameterStrategy?: ForecastRunRequest["parameterStrategy"];
  progress: ForecastProgress | null;
  runtimeDetail?: RuntimeRunDetail | null;
}) {
  const [drawerModelKey, setDrawerModelKey] = useState("");
  const items = finalForecastMode
    ? ["读取完整历史数据", "重新训练最终模型", "生成未来预测", "更新预测图表"]
    : parameterStrategy === "auto"
      ? ["校验字段配置", "清洁并构建序列", "自动优化参数", "运行模型回测", "计算残差指标"]
      : ["校验字段配置", "清洁并构建序列", "运行模型回测", "计算残差指标"];
  const modelMap = new Map(models.map((model) => [model.id, model]));
  const modelIds = finalForecastMode ? [finalModelId].filter(Boolean) : selectedModelIds;
  const runningModels = modelIds.map((modelId) => {
    const model = modelMap.get(modelId);
    return {
      id: modelId,
      name: model?.name ?? modelId,
      family: model?.modelFamily || model?.category || "模型",
      requiresGpu: Boolean(model?.requiresGpu)
    };
  });
  const statusMeta = {
    queued: { label: "排队中", tone: "neutral" },
    tuning: { label: "自动优化", tone: "info" },
    fitting: { label: "拟合中", tone: "info" },
    predicting: { label: "预测中", tone: "info" },
    scoring: { label: "计算指标", tone: "warn" },
    success: { label: "已完成", tone: "good" },
    failed: { label: "失败", tone: "bad" }
  } as const;
  const runtimeModelMap = new Map((runtimeDetail?.models ?? []).map((model) => [`${model.targetColumn}:${model.modelId}`, model] as const));
  const progressModelMap = new Map((progress?.models ?? []).map((row) => [`${row.targetColumn}:${row.modelId}`, row] as const));
  const progressRows = runtimeDetail?.models.length
    ? runtimeDetail.models.map((runtimeModel) => {
        const progressRow = progressModelMap.get(`${runtimeModel.targetColumn}:${runtimeModel.modelId}`);
        const currentStatus = progressRow?.status ?? runtimeModel.status;
        return {
          key: `${runtimeModel.targetColumn}:${runtimeModel.modelId}`,
          id: runtimeModel.modelId,
          name: progressRow?.modelName ?? runtimeModel.modelName,
          family: modelMap.get(runtimeModel.modelId)?.modelFamily || modelMap.get(runtimeModel.modelId)?.category || "模型",
          requiresGpu: Boolean(modelMap.get(runtimeModel.modelId)?.requiresGpu),
          targetColumn: runtimeModel.targetColumn,
          percent: progressRow?.percent ?? runtimeModel.progressPercent,
          status: currentStatus,
          message: progressRow?.message ?? runtimeModel.message,
          fitSeconds: progressRow?.fitSeconds ?? runtimeModel.fitSeconds,
          predictSeconds: progressRow?.predictSeconds ?? runtimeModel.predictSeconds,
          error: progressRow?.error ?? runtimeModel.error,
          displayStatus: statusMeta[currentStatus],
          runtimeModel
        };
      })
    : progress?.models.length
      ? progress.models.map((row) => ({
        ...row,
        key: `${row.targetColumn}:${row.modelId}`,
        id: row.modelId,
        name: row.modelName,
        family: modelMap.get(row.modelId)?.modelFamily || modelMap.get(row.modelId)?.category || "模型",
        requiresGpu: Boolean(modelMap.get(row.modelId)?.requiresGpu),
        displayStatus: statusMeta[row.status],
        runtimeModel: runtimeModelMap.get(`${row.targetColumn}:${row.modelId}`) ?? null
      }))
      : runningModels.map((model) => ({
        ...model,
        key: `:${model.id}`,
        targetColumn: "",
        percent: 0,
        status: "queued" as const,
        message: "等待后端接收任务。",
        fitSeconds: null,
        predictSeconds: null,
        error: null,
        displayStatus: statusMeta.queued,
        runtimeModel: null
      }));
  const effectiveCompletedModels = progress?.completedModels ?? runtimeDetail?.models.filter((model) => model.status === "success" || model.status === "failed").length ?? 0;
  const effectiveTotalModels = progress?.totalModels ?? runtimeDetail?.models.length ?? runningModels.length;
  const effectiveStatus = progress?.status ?? runtimeDetail?.status ?? "running";
  const overallProgress = progress?.overallPercent ?? runtimeDetail?.overallPercent ?? 1;
  const effectiveMessage = progress?.message ?? runtimeDetail?.message ?? "正在初始化后端进度流。";
  const phaseIndex = (() => {
    const phase = progress?.phase ?? (() => {
      switch (runtimeDetail?.currentStage) {
        case "loading":
          return "parsing";
        case "cleaning":
        case "feature_engineering":
        case "feature_selection":
          return "building_series";
        case "auto_tuning":
          return "model_tuning";
        case "training":
        case "forecast":
          return "model_fitting";
        case "residual_analysis":
          return "ranking";
        case "finished":
          return "completed";
        case "failed":
          return "failed";
        default:
          return "preparing";
      }
    })();
    if (finalForecastMode) {
      if (phase === "fitting" || phase === "predicting") return 2;
      if (phase === "saving" || phase === "completed") return 3;
      if (phase === "parsing" || phase === "profiling" || phase === "building_series") return 1;
      return 0;
    }
    if (phase === "model_tuning") return 2;
    if (phase.startsWith("model_") || phase === "fitting" || phase === "predicting") return parameterStrategy === "auto" ? 3 : 2;
    if (phase === "ranking" || phase === "saving" || phase === "completed") return parameterStrategy === "auto" ? 4 : 3;
    if (phase === "parsing" || phase === "profiling" || phase === "building_series") return 1;
    return 0;
  })();

  useEffect(() => {
    if (!progressRows.length) return;
    if (drawerModelKey && !progressRows.some((model) => model.key === drawerModelKey)) {
      setDrawerModelKey("");
    }
  }, [drawerModelKey, progressRows]);

  return (
    <SectionCard
      title={finalForecastMode ? "正在运行最终预测" : "正在运行预测实验"}
      description={finalForecastMode ? "后端正在用完整历史重新拟合最终模型并生成预测。" : parameterStrategy === "auto" ? "进度来自后端真实阶段事件；自动优化会单独显示候选参数搜索进度。" : "进度来自后端真实阶段事件；模型库不提供内部迭代百分比时，展示拟合、预测和指标计算阶段。"}
      className="overflow-hidden"
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-2xl font-semibold text-slate-950 dark:text-white">{overallProgress}%</div>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            已运行 {formatElapsed(elapsedSeconds)} · {effectiveMessage}
          </div>
        </div>
        <Badge tone={effectiveStatus === "failed" ? "bad" : effectiveStatus === "completed" ? "good" : "info"}>
          {finalForecastMode && !effectiveTotalModels ? "最终预测" : `${effectiveCompletedModels}/${effectiveTotalModels} 个模型完成`}
        </Badge>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700"
          style={{ width: `${overallProgress}%` }}
        />
      </div>
      <div className={`mt-4 grid gap-2 ${items.length === 5 ? "md:grid-cols-5" : "md:grid-cols-4"}`}>
        {items.map((item, index) => (
          <div
            key={item}
            className={`rounded-xl border px-3 py-2 text-xs font-medium ${
              index <= phaseIndex
                ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-300"
                : "border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300"
            }`}
          >
            {item}
          </div>
        ))}
      </div>
      {progressRows.length ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {progressRows.map((model) => {
            const runtimeModel = model.runtimeModel;
            return (
              <button
                key={model.key}
                type="button"
                aria-expanded={drawerModelKey === model.key}
                onClick={() => setDrawerModelKey((current) => (current === model.key ? "" : model.key))}
                className={`min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-3 text-left transition dark:border-white/10 dark:bg-[#151b2e] ${
                  drawerModelKey === model.key ? "ring-1 ring-cyan-300 dark:ring-cyan-400/40" : "hover:border-slate-300 dark:hover:border-white/20"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="truncate text-sm font-semibold text-slate-950 dark:text-white">{model.name}</div>
                      <span className="text-[11px] text-slate-400 dark:text-slate-500">{drawerModelKey === model.key ? "▾" : "▸"}</span>
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {model.family}{model.targetColumn ? ` / ${model.targetColumn}` : ""}{model.requiresGpu ? " / 建议 GPU" : ""}
                    </div>
                  </div>
                  <Badge tone={model.displayStatus.tone}>{model.displayStatus.label}</Badge>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                  <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all duration-500" style={{ width: `${model.percent}%` }} />
                </div>
                <div className="mt-2 flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
                  <span className="min-w-0 break-words">{model.percent}% · {model.message}</span>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>{runtimeModel ? `阶段 ${runtimeStageCompactLabel(runtimeModel.currentStage)}` : "等待后端阶段事件"}</span>
                    <span className="shrink-0">
                      {model.fitSeconds !== null ? `拟合 ${model.fitSeconds.toFixed(2)}s` : ""}
                      {model.predictSeconds !== null ? ` / 预测 ${model.predictSeconds.toFixed(2)}s` : ""}
                    </span>
                  </div>
                </div>
                {model.error ? <div className="mt-2 text-xs text-red-600 dark:text-red-300">{model.error}</div> : null}
              </button>
            );
          })}
        </div>
      ) : null}
      <RuntimeModelConsoleDrawer
        runtime={runtimeDetail}
        selectedModelKey={drawerModelKey}
        open={Boolean(drawerModelKey && runtimeDetail)}
        onClose={() => setDrawerModelKey("")}
      />
    </SectionCard>
  );
}

function ModelParameterControls({
  modelId,
  parameters,
  onChange
}: {
  modelId: string;
  parameters: Record<string, ModelParameterValue>;
  onChange: (key: string, value: ModelParameterValue) => void;
}) {
  const fields = modelParameterFields[modelId] ?? [];
  if (!fields.length) {
    return <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-[#0b1020] dark:text-slate-400">该模型暂无额外可调参数。</div>;
  }
  return (
    <div className="grid gap-3">
      {fields.map((field) => {
        const value = parameters[field.key] ?? modelParameterDefaults[modelId]?.[field.key] ?? (field.type === "boolean" ? false : "");
        const help = getParameterHelp(modelId, field.key);
        if (field.type === "select") {
          return (
            <label key={field.key} className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
              <div className="flex items-center gap-2">
                <span className="font-medium">{help?.title ?? field.label}</span>
                {help ? <span className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-slate-300 text-[10px] text-slate-500 dark:border-white/20 dark:text-slate-300" title={`${help.description} 建议：${help.recommended}`}>?</span> : null}
              </div>
              <select className={`${controls.input} h-9 text-xs`} value={String(value)} onChange={(event) => onChange(field.key, event.target.value)}>
                {(field.options ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {help ? <p className="text-[11px] leading-5 text-slate-500 dark:text-slate-400">{help.description} 建议：{help.recommended}</p> : null}
            </label>
          );
        }
        if (field.type === "boolean") {
          return (
            <label key={field.key} className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
              <div className="flex items-center gap-2 font-medium">
                <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(field.key, event.target.checked)} />
                <span>{help?.title ?? field.label}</span>
                {help ? <span className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-slate-300 text-[10px] text-slate-500 dark:border-white/20 dark:text-slate-300" title={`${help.description} 建议：${help.recommended}`}>?</span> : null}
              </div>
              {help ? <p className="pl-6 text-[11px] leading-5 text-slate-500 dark:text-slate-400">{help.description} 建议：{help.recommended}</p> : null}
            </label>
          );
        }
        return (
          <label key={field.key} className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
            <div className="flex items-center gap-2">
              <span className="font-medium">{help?.title ?? field.label}</span>
              {help ? <span className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-slate-300 text-[10px] text-slate-500 dark:border-white/20 dark:text-slate-300" title={`${help.description} 增大：${help.increaseEffect} 减小：${help.decreaseEffect} 建议：${help.recommended}`}>?</span> : null}
            </div>
            <input
              className={`${controls.input} h-9 text-xs`}
              type="number"
              min={field.min}
              max={field.max}
              step={field.step}
              value={Number(value)}
              onChange={(event) => {
                const next = Number(event.target.value);
                if (Number.isFinite(next)) onChange(field.key, next);
              }}
            />
            {help ? <p className="text-[11px] leading-5 text-slate-500 dark:text-slate-400">{help.description} 增大：{help.increaseEffect} 减小：{help.decreaseEffect}</p> : null}
          </label>
        );
      })}
    </div>
  );
}

function ModelCard({
  model,
  selected,
  resource,
  runtimeEstimate,
  parameters,
  onChange,
  onParameterChange
}: {
  model: ModelCapability;
  selected: boolean;
  resource: ModelResourceAssessment;
  runtimeEstimate?: RuntimeEstimateItem;
  parameters: Record<string, ModelParameterValue>;
  onChange: (checked: boolean) => void;
  onParameterChange: (key: string, value: ModelParameterValue) => void;
}) {
  const runnable = isRunnableModel(model) && resource.level !== "gray";
  const toggleDisabled = !runnable && !selected;
  return (
    <div
      className={`rounded-2xl border p-4 text-left transition ${
        selected
          ? "border-indigo-400 bg-indigo-50 shadow-sm dark:border-indigo-300/40 dark:bg-indigo-400/10"
          : "border-slate-200 bg-white hover:border-slate-300 dark:border-white/10 dark:bg-[#151b2e] dark:hover:border-white/20"
      } ${runnable ? "" : "opacity-60"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-semibold text-slate-950 dark:text-white">
            <span className={`h-2.5 w-2.5 rounded-full shadow-lg ${resourceToneClass[resource.level]}`} />
            <span className="truncate">{model.name}</span>
          </div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{model.modelFamily || model.category}</div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Badge tone={modelStatusTone(model)}>{modelStatusText(model)}</Badge>
          <label className={`inline-flex items-center gap-2 text-xs font-semibold ${toggleDisabled ? "cursor-not-allowed text-slate-400" : "cursor-pointer text-indigo-600 dark:text-indigo-200"}`}>
            <input type="checkbox" disabled={toggleDisabled} checked={selected} onChange={(event) => onChange(event.target.checked)} />
            {selected ? "已选择" : "选择"}
          </label>
        </div>
      </div>
      <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{zhCN.modelDescriptions[model.id as keyof typeof zhCN.modelDescriptions] ?? model.shortDescription}</p>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-xl bg-slate-50 px-3 py-2 text-slate-600 dark:bg-[#0b1020] dark:text-slate-300">
          <div className="text-slate-400 dark:text-slate-500">负荷</div>
          <div className="mt-1 font-semibold">{resource.label}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2 text-slate-600 dark:bg-[#0b1020] dark:text-slate-300">
          <div className="text-slate-400 dark:text-slate-500">最小 RAM</div>
          <div className="mt-1 font-semibold">{formatMemory(resource.minRamMb)}</div>
        </div>
      </div>
      {runtimeEstimate ? (
        <div className="mt-2 rounded-xl border border-cyan-200 bg-cyan-50/80 px-3 py-2 text-xs text-cyan-900 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-cyan-700 dark:text-cyan-200">预计运行时间</div>
              <div className="mt-1 font-semibold">{formatCompactDuration(runtimeEstimate.estimatedSeconds)}</div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <Badge tone={runtimeConfidenceTone(runtimeEstimate.confidence)}>{runtimeEstimate.confidence === "high" ? "高置信" : runtimeEstimate.confidence === "medium" ? "中置信" : "低置信"}</Badge>
              <span className="text-[11px] text-cyan-700/80 dark:text-cyan-100/80">{runtimeEstimate.computeTarget.toUpperCase()}</span>
            </div>
          </div>
        </div>
      ) : null}
      <p className={`mt-2 text-xs ${resource.level === "red" || resource.level === "gray" ? "text-amber-600 dark:text-amber-300" : "text-slate-500 dark:text-slate-400"}`}>
        {resource.reason}
      </p>
      {!runnable && model.unavailableReason && resource.reason !== model.unavailableReason ? <p className="mt-2 text-xs text-amber-600 dark:text-amber-300">{model.unavailableReason}</p> : null}
      {runnable ? (
        <details className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white/70 dark:border-white/10 dark:bg-[#0b1020]/70">
          <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-700 dark:text-slate-200">高级设置</summary>
          <div className="border-t border-slate-200 p-3 dark:border-white/10">
            <ModelParameterControls modelId={model.id} parameters={parameters} onChange={onParameterChange} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ResultsDashboard({
  result,
  finalForecast,
  finalModelId,
  setFinalModelId,
  submitFinalForecast,
  chartModelIds,
  setChartModelIds,
  metric,
  setMetric
}: {
  result: ForecastRunResponse;
  finalForecast: ReturnType<typeof useLabStore.getState>["finalForecast"];
  finalModelId: string;
  setFinalModelId: (modelId: string) => void;
  submitFinalForecast: () => void;
  chartModelIds: string[];
  setChartModelIds: Dispatch<SetStateAction<string[]>>;
  metric: "mae" | "mse" | "rmse" | "wape";
  setMetric: (metric: "mae" | "mse" | "rmse" | "wape") => void;
}) {
  const [tab, setTab] = useState<ResultTab>("dataHealth");
  const best = result.rankedModels.find((model) => model.rank === 1 && model.metrics);
  const successfulModels = result.rankedModels.filter((model) => model.status === "success");
  const chartableModelIds = successfulModels.filter((model) => result.backtest.predictions[model.modelId]).map((model) => model.modelId);
  const selectedChartModelCount = chartableModelIds.filter((modelId) => chartModelIds.includes(modelId)).length;
  const allModelsVisible = chartableModelIds.length > 0 && selectedChartModelCount === chartableModelIds.length;
  const showAllRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (showAllRef.current) {
      showAllRef.current.indeterminate = selectedChartModelCount > 0 && !allModelsVisible;
    }
  }, [allModelsVisible, selectedChartModelCount]);

  return (
    <section className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-7">
        <StatCard label="目标列" value={result.targetColumn} hint="当前分析目标" tone="info" />
        <StatCard label="时间范围" value={result.diagnostics.timeStart ?? "-"} hint={result.diagnostics.timeEnd ?? "结束时间未知"} />
        <StatCard label="样本数" value={result.diagnostics.validRowCount} hint={`丢弃 ${result.diagnostics.droppedRowCount} 行`} />
        <StatCard label="数据健康" value={`${result.dataHealth.score}/100`} hint={`等级：${dataHealthLevelText(result.dataHealth.level)}`} tone={dataHealthTone(result.dataHealth.level)} />
        <StatCard label="推荐模型" value={result.recommendedModelId ?? "暂无"} hint="按 MAE 最低推荐" tone="good" />
        <StatCard label="最佳 MAE" value={metricText(best?.metrics?.mae)} hint="越低越好" tone="good" />
        <StatCard label="最佳 WAPE" value={metricText(best?.metrics?.wape)} hint="总绝对误差占比" tone="warn" />
      </div>

      <SectionCard title="数据健康快照" description="清洁只作用于本次实验构建的时间序列，不修改上传原文件。">
        <div className="grid divide-y divide-slate-200 border-y border-slate-200 dark:divide-white/10 dark:border-white/10 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-6">
          {[
            ["无效时间", result.diagnostics.invalidTimeCount],
            ["目标缺失", result.diagnostics.inputMissingTargetCount],
            ["无效数值", result.diagnostics.invalidTargetCount],
            ["重复时间", result.diagnostics.duplicateTimeCount],
            ["已补数值", result.diagnostics.filledValueCount],
            ["异常值调整", `${result.diagnostics.outlierAdjustedCount}/${result.diagnostics.outlierCount}`]
          ].map(([label, value]) => (
            <div key={label} className="px-4 py-3">
              <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
              <div className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">{value}</div>
            </div>
          ))}
        </div>
        {result.diagnostics.cleaningActions.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {result.diagnostics.cleaningActions.map((action) => <Badge key={action} tone="neutral">{action}</Badge>)}
          </div>
        ) : null}
      </SectionCard>

      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        <div className={`${surface.chartPanel} min-h-[460px]`}>
          <ActualVsPredictedChart result={result} visibleModelIds={chartModelIds} height={430} />
        </div>
        <SectionCard title="AI Insights" description="推荐模型、失败隔离和最终预测入口。">
          <div className="space-y-4">
            <div className="rounded-2xl bg-slate-50 p-4 dark:bg-[#151b2e]">
              <div className="text-xs text-slate-500 dark:text-slate-400">推荐最佳模型</div>
              <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">{best?.modelName ?? "暂无"}</div>
              <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">推荐原因：测试集 MAE 最低。失败模型已被保留在排行榜，但不参与推荐。数据健康分可帮助判断当前结论的可信度。</p>
            </div>
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">最终模型</span>
              <select className={controls.input} value={finalModelId} onChange={(event) => setFinalModelId(event.target.value)}>
                {successfulModels.map((model) => (
                  <option key={model.modelId} value={model.modelId}>
                    {model.modelName}
                  </option>
                ))}
              </select>
            </label>
            <button className={`${controls.primaryButton} w-full`} onClick={submitFinalForecast}>
              运行最终预测
            </button>
            <a className={`${controls.secondaryButton} w-full`} href="#ai-report">
              一键生成报告
            </a>
            <div>
              <div className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-200">图表显示模型</div>
              <label className="mb-2 flex items-center justify-between rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 dark:border-indigo-400/20 dark:bg-indigo-400/10 dark:text-indigo-200">
                <span>显示全部模型</span>
                <input
                  ref={showAllRef}
                  type="checkbox"
                  checked={allModelsVisible}
                  onChange={(event) => setChartModelIds(event.target.checked ? chartableModelIds : defaultVisibleModelIds(result))}
                />
              </label>
              <div className="space-y-2">
                {successfulModels
                  .filter((model) => result.backtest.predictions[model.modelId])
                  .map((model) => (
                    <label key={model.modelId} className="flex items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-white/10">
                      <span>{model.modelName}</span>
                      <input
                        type="checkbox"
                        checked={chartModelIds.includes(model.modelId)}
                        onChange={(event) => setChartModelIds((current) => (event.target.checked ? Array.from(new Set([...current, model.modelId])) : current.filter((modelId) => modelId !== model.modelId)))}
                      />
                    </label>
                  ))}
              </div>
            </div>
          </div>
        </SectionCard>
      </div>

      <Tabs<ResultTab>
        value={tab}
        onChange={setTab}
        items={[
          { id: "dataHealth", label: "数据健康" },
          { id: "overview", label: "预测对比" },
          { id: "residual", label: "残差诊断" },
          { id: "metrics", label: "指标排名" },
          { id: "distribution", label: "误差分布" },
          { id: "featureFactory", label: "特征工厂" },
          { id: "explainability", label: "特征解释" },
          { id: "final", label: "最终预测" },
          { id: "reproducibility", label: "实验复现" },
          { id: "report", label: "AI 报告" }
        ]}
      />

      {tab === "dataHealth" ? <DataHealthPanel dataHealth={result.dataHealth} /> : null}

      {tab === "overview" ? (
        <div className="grid gap-5 xl:grid-cols-2">
          <div className={surface.chartPanel}><ActualVsPredictedChart result={result} visibleModelIds={chartModelIds} /></div>
          <div className={surface.chartPanel}><MetricBarChart result={result} metric={metric} /></div>
        </div>
      ) : null}

      {tab === "residual" ? (
        <div className="grid gap-5 xl:grid-cols-2">
          <div className={surface.chartPanel}><ResidualTimelineChart result={result} visibleModelIds={chartModelIds} /></div>
          <div className={surface.chartPanel}><PredictedResidualScatterChart result={result} visibleModelIds={chartModelIds} /></div>
          <div className={surface.chartPanel}><AbsoluteErrorTimelineChart result={result} visibleModelIds={chartModelIds} /></div>
        </div>
      ) : null}

      {tab === "metrics" ? (
        <SectionCard
          title="模型排行榜"
          description="默认按 MAE 从小到大排序，失败模型保留原因但不参与推荐。"
          action={
            <select className={controls.input} value={metric} onChange={(event) => setMetric(event.target.value as typeof metric)}>
              <option value="mae">MAE</option>
              <option value="mse">MSE</option>
              <option value="rmse">RMSE</option>
              <option value="wape">WAPE</option>
            </select>
          }
        >
          <div className="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
            <ModelLeaderboard rows={result.rankedModels} recommendedModelId={result.recommendedModelId} />
            <div className={surface.chartPanel}><NormalizedMetricChart result={result} /></div>
          </div>
        </SectionCard>
      ) : null}

      {tab === "distribution" ? (
        <div className="grid gap-5 xl:grid-cols-2">
          <div className={surface.chartPanel}><ResidualDistributionChart result={result} visibleModelIds={chartModelIds} /></div>
          <div className={surface.chartPanel}><AbsoluteErrorTimelineChart result={result} visibleModelIds={chartModelIds} /></div>
        </div>
      ) : null}

      {tab === "featureFactory" ? <FeatureFactoryPanel experimentId={result.experimentId} /> : null}

      {tab === "explainability" ? <ExplainabilityPanel experimentId={result.experimentId} recommendedModelId={result.recommendedModelId} /> : null}

      {tab === "final" ? (
        <div className={surface.chartPanel}><FinalForecastChart finalForecast={finalForecast} /></div>
      ) : null}

      {tab === "reproducibility" ? <ReproducibilityPanel experimentId={result.experimentId} manifest={result.manifest} /> : null}

      {tab === "report" ? (
        <div id="ai-report">
          <ReportPanel
            experimentId={result.experimentId}
            visualization={{
              result,
              finalForecast,
              visibleModelIds: chartModelIds,
              metric
            }}
          />
        </div>
      ) : null}
    </section>
  );
}

export function ForecastPage() {
  const { currentUser, upload, selectedSheet, forecastResult, finalForecast, rerunDraft, setForecastResult, setFinalForecast, setRerunDraft } = useLabStore();
  const [persistedSelection] = useState(loadPersistedSelectedModels);
  const [models, setModels] = useState<ModelCapability[]>([]);
  const [device, setDevice] = useState("cpu");
  const [deviceInfo, setDeviceInfo] = useState<DeviceInfo | null>(null);
  const [dataMode, setDataMode] = useState<"aggregated" | "raw">("aggregated");
  const [timeColumn, setTimeColumn] = useState("");
  const [targetColumns, setTargetColumns] = useState<string[]>([]);
  const [covariateColumns, setCovariateColumns] = useState<string[]>([]);
  const [aggregationMethod, setAggregationMethod] = useState<ForecastRunRequest["aggregation"]["method"]>("sum");
  const [cleaningPreset, setCleaningPreset] = useState<CleaningConfig["preset"]>("standard");
  const [missingValueStrategy, setMissingValueStrategy] = useState<ForecastRunRequest["missingValueStrategy"]>("time");
  const [fillMissingTimeSteps, setFillMissingTimeSteps] = useState(true);
  const [duplicateTimeStrategy, setDuplicateTimeStrategy] = useState<ForecastRunRequest["duplicateTimeStrategy"]>("mean");
  const [outlierStrategy, setOutlierStrategy] = useState<ForecastRunRequest["outlierStrategy"]>("none");
  const [outlierIqrMultiplier, setOutlierIqrMultiplier] = useState(1.5);
  const [invalidTimeStrategy, setInvalidTimeStrategy] = useState<CleaningConfig["invalidTimeStrategy"]>("drop");
  const [interpolationLimit, setInterpolationLimit] = useState<number | null>(3);
  const [hampelWindow, setHampelWindow] = useState(7);
  const [hampelSigma, setHampelSigma] = useState(3);
  const [advancedCleaning, setAdvancedCleaning] = useState(false);
  const [covariateConfigs, setCovariateConfigs] = useState<Record<string, CovariateConfig>>({});
  const [holidayConfig, setHolidayConfig] = useState<HolidayConfig>(defaultHolidayConfig);
  const [holidayCatalog, setHolidayCatalog] = useState<HolidayCalendarCatalog | null>(null);
  const [horizon, setHorizon] = useState(7);
  const [testSize, setTestSize] = useState(7);
  const [selectedModels, setSelectedModels] = useState<string[]>(persistedSelection.values);
  const [runtimeEstimates, setRuntimeEstimates] = useState<RuntimeEstimateItem[]>([]);
  const [modelParameters, setModelParameters] = useState<Record<string, Record<string, ModelParameterValue>>>(modelParameterDefaults);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfig>(defaultFeatureConfig);
  const [runProfile, setRunProfile] = useState<ForecastRunRequest["runProfile"]>("balanced");
  const [parameterStrategy, setParameterStrategy] = useState<ForecastRunRequest["parameterStrategy"]>("default");
  const [randomSeed] = useState(42);
  const [metric, setMetric] = useState<"mae" | "mse" | "rmse" | "wape">("mae");
  const [finalModelId, setFinalModelId] = useState("");
  const [chartModelIds, setChartModelIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [progressNow, setProgressNow] = useState(Date.now());
  const [runProgress, setRunProgress] = useState<ForecastProgress | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runtimeDetail, setRuntimeDetail] = useState<RuntimeRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leakageDialogColumn, setLeakageDialogColumn] = useState<string | null>(null);
  const [leakageDialogRemember, setLeakageDialogRemember] = useState(false);
  const [suppressLeakageWarning, setSuppressLeakageWarning] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const remembered = window.localStorage.getItem(leakageReminderStorageKey(currentUser?.userId));
    setSuppressLeakageWarning(remembered === "1");
  }, [currentUser?.userId]);

  useEffect(() => {
    void fetchModels()
      .then((modelList) => {
        setModels(modelList);
        const runnableDefaults = modelList.filter((model) => modelDefaults.includes(model.id) && isRunnableModel(model)).map((model) => model.id);
        setSelectedModels((current) => (current.length || persistedSelection.hasValue ? current : runnableDefaults));
      })
      .catch(() => undefined);
    void fetchHolidayCalendars().then(setHolidayCatalog).catch(() => undefined);
    void fetchDeviceInfo()
      .then((info) => {
        setDeviceInfo(info);
        setDevice(info.device);
      })
      .catch(() => {
        setDeviceInfo({
          device: "cpu",
          memoryTotalMb: null,
          memoryAvailableMb: null,
          accelerator: {
            hardwareDetected: false,
            runtimeAvailable: false,
            type: null,
            name: null,
            memoryTotalMb: null,
            driverVersion: null,
            frameworkVersion: null,
            frameworkBuild: null,
            cudaRuntime: null,
            reason: "设备状态接口不可用。"
          }
        });
        setDevice("cpu");
      });
  }, []);

  useEffect(() => {
    if (!selectedSheet) return;
    const firstTime = selectedSheet.columns.find((column) => column.inferredType === "datetime")?.name ?? selectedSheet.columns[0]?.name ?? "";
    const firstNumber = selectedSheet.columns.find((column) => column.inferredType === "number")?.name ?? selectedSheet.columns[1]?.name ?? "";
    const nextTargetColumns = firstNumber ? [firstNumber] : [];
    setTimeColumn(firstTime);
    setTargetColumns(nextTargetColumns);
    const nextCovariates = selectedSheet.columns
      .filter((column) => (column.inferredType === "number" || column.inferredType === "boolean") && column.name !== firstTime && !nextTargetColumns.includes(column.name))
      .map((column) => column.name);
    setCovariateColumns(nextCovariates);
    setCovariateConfigs(Object.fromEntries(nextCovariates.map((column) => [column, covariateDefaults(column)])));
    setFeatureConfig(defaultFeatureConfig);
    setHolidayConfig(defaultHolidayConfig);
  }, [selectedSheet]);

  useEffect(() => {
    if (forecastResult?.recommendedModelId) {
      setFinalModelId(forecastResult.recommendedModelId);
      setChartModelIds(defaultVisibleModelIds(forecastResult));
    }
  }, [forecastResult]);

  useEffect(() => {
    if (!rerunDraft || !upload || !selectedSheet || forecastResult) return;
    if (rerunDraft.fileMatch.uploadId && rerunDraft.fileMatch.uploadId !== upload.uploadId) return;
    const template = rerunDraft.runRequestTemplate as Partial<ForecastRunRequest>;
    setDataMode(template.dataMode ?? "aggregated");
    setTimeColumn(template.timeColumn ?? selectedSheet.columns.find((column) => column.inferredType === "datetime")?.name ?? "");
    setTargetColumns(template.targetColumns ?? []);
    setCovariateColumns(template.covariateColumns ?? []);
    setAggregationMethod(template.aggregation?.method ?? "sum");
    const savedCleaning = template.cleaningConfig;
    setCleaningPreset(savedCleaning?.preset ?? "custom");
    setMissingValueStrategy(savedCleaning?.missingValueStrategy ?? template.missingValueStrategy ?? "drop");
    setFillMissingTimeSteps(savedCleaning?.fillMissingTimeSteps ?? template.fillMissingTimeSteps ?? true);
    setDuplicateTimeStrategy(savedCleaning?.duplicateTimeStrategy ?? template.duplicateTimeStrategy ?? "mean");
    setOutlierStrategy(savedCleaning?.outlierStrategy ?? template.outlierStrategy ?? "none");
    setOutlierIqrMultiplier(savedCleaning?.outlierIqrMultiplier ?? template.outlierIqrMultiplier ?? 1.5);
    setInvalidTimeStrategy(savedCleaning?.invalidTimeStrategy ?? "drop");
    setInterpolationLimit(savedCleaning?.interpolationLimit ?? 3);
    setHampelWindow(savedCleaning?.hampelWindow ?? 7);
    setHampelSigma(savedCleaning?.hampelSigma ?? 3);
    setCovariateConfigs(Object.fromEntries((template.covariateConfigs ?? []).map((item) => [item.column, normalizeCovariateConfig(item.column, item)])));
    setHolidayConfig(template.holidayConfig ?? defaultHolidayConfig);
    setHorizon(template.horizon ?? 7);
    setTestSize(template.testSize ?? 7);
    setSelectedModels(template.selectedModels ?? []);
    setModelParameters({
      ...modelParameterDefaults,
      ...(template.modelParameters ?? {})
    });
    setFeatureConfig({
      ...defaultFeatureConfig,
      ...(template.featureConfig ?? {})
    });
    setRunProfile(template.runProfile ?? "balanced");
    setParameterStrategy(template.parameterStrategy ?? "default");
  }, [forecastResult, rerunDraft, selectedSheet, upload]);

  useEffect(() => {
    const runnableModelIds = models.filter((model) => isRunnableModel(model)).map((model) => model.id);
    if (!selectedSheet || !runnableModelIds.length || forecastResult) {
      setRuntimeEstimates([]);
      return;
    }
    let cancelled = false;
    void fetchRuntimeEstimate({
      rowCount: Math.max(selectedSheet.rowCountApprox ?? selectedSheet.previewRows.length ?? 1, 1),
      frequency: "auto",
      totalColumnCount: Math.max(selectedSheet.columns.length, 1),
      targetCount: Math.max(targetColumns.length, 1),
      covariateCount: covariateColumns.length,
      unknownFutureForecastCount: 0,
      perPrimaryModelCovariateCount: 0,
      featureConfig,
      runProfile,
      parameterStrategy,
      device,
      selectedModels: runnableModelIds
    })
      .then((response) => {
        if (!cancelled) setRuntimeEstimates(response.models);
      })
      .catch(() => {
        if (!cancelled) setRuntimeEstimates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [covariateColumns, covariateConfigs, device, featureConfig, forecastResult, models, parameterStrategy, runProfile, selectedSheet, targetColumns.length]);

  useEffect(() => {
    if (!loading || runStartedAt === null) return;
    setProgressNow(Date.now());
    const timer = window.setInterval(() => setProgressNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [loading, runStartedAt]);

  useEffect(() => {
    if (!activeRunId || !loading) return;
    let cancelled = false;
    let timer = 0;

    const load = async () => {
      try {
        const detail = await fetchRuntimeDetail(activeRunId);
        if (cancelled) return;
        setRuntimeDetail(detail);
        if (detail.status === "running") {
          timer = window.setTimeout(() => void load(), 1200);
        }
      } catch {
        if (!cancelled) {
          timer = window.setTimeout(() => void load(), 1500);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeRunId, loading]);

  useEffect(() => {
    if (!activeRunId || !loading) return;
    let cancelled = false;
    const stop = subscribeRuntimeEvents(activeRunId, (event) => {
      if (event.eventType !== "feature" || cancelled) return;
      void fetchRuntimeDetail(activeRunId)
        .then((detail) => {
          if (!cancelled) setRuntimeDetail(detail);
        })
        .catch(() => undefined);
    });
    return () => {
      cancelled = true;
      stop();
    };
  }, [activeRunId, loading]);

  const orderedColumns = useMemo(() => {
    if (!selectedSheet) return [];
    return [...selectedSheet.columns].sort((left, right) => {
      const score = (type: string) => (type === "datetime" ? 0 : type === "number" ? 1 : 2);
      return score(left.inferredType) - score(right.inferredType);
    });
  }, [selectedSheet]);

  const availableCovariateColumns = useMemo(() => {
    return orderedColumns.filter(
      (column) =>
        (column.inferredType === "number" || column.inferredType === "boolean") &&
        column.name !== timeColumn &&
        !targetColumns.includes(column.name)
    );
  }, [orderedColumns, targetColumns, timeColumn]);

  useEffect(() => {
    const allowed = new Set(availableCovariateColumns.map((column) => column.name));
    setCovariateColumns((current) => current.filter((column) => allowed.has(column)));
  }, [availableCovariateColumns]);

  const resourceAssessments = useMemo(() => {
    return new Map(
      models.map((model) => [
        model.id,
        assessModelResource({
          model,
          deviceInfo,
          upload,
          sheet: selectedSheet,
          dataMode,
          targetColumns,
          horizon,
          testSize
        })
      ])
    );
  }, [models, deviceInfo, upload, selectedSheet, dataMode, targetColumns, horizon, testSize]);

  const sortedModels = useMemo(() => {
    const levelOrder: Record<ResourceLevel, number> = { green: 0, yellow: 1, red: 2, gray: 3 };
    return [...models].sort((left, right) => {
      const leftResource = resourceAssessments.get(left.id);
      const rightResource = resourceAssessments.get(right.id);
      const levelDiff = levelOrder[leftResource?.level ?? "gray"] - levelOrder[rightResource?.level ?? "gray"];
      if (levelDiff !== 0) return levelDiff;
      const ramDiff = (leftResource?.minRamMb ?? Number.MAX_SAFE_INTEGER) - (rightResource?.minRamMb ?? Number.MAX_SAFE_INTEGER);
      if (ramDiff !== 0) return ramDiff;
      return left.priority - right.priority;
    });
  }, [models, resourceAssessments]);
  const runtimeEstimateMap = useMemo(() => new Map(runtimeEstimates.map((item) => [item.id, item])), [runtimeEstimates]);

  useEffect(() => {
    if (!models.length) return;
    const knownIds = new Set(models.map((model) => model.id));
    setSelectedModels((current) => current.filter((modelId) => knownIds.has(modelId)));
  }, [models]);

  useEffect(() => {
    persistSelectedModels(selectedModels);
  }, [selectedModels]);

  const horizonRange = useMemo(() => {
    const selected = models.filter((model) => selectedModels.includes(model.id));
    if (!selected.length) return { min: 1, max: 1, compatible: false };
    const min = Math.max(...selected.map((model) => model.minHorizon));
    const max = Math.min(...selected.map((model) => model.maxHorizon));
    return { min, max, compatible: min <= max };
  }, [models, selectedModels]);
  const selectedFeatureAwareModels = useMemo(
    () => models.filter((model) => selectedModels.includes(model.id) && model.supportsCovariates),
    [models, selectedModels]
  );
  const featureConfigHasAnyEnabled = useMemo(() => Object.values(featureConfig).some(Boolean), [featureConfig]);
  const modelRunCount = targetColumns.length * selectedModels.length;
  const heavyModelRunCount = targetColumns.length * selectedModels.filter((modelId) => heavyModelIds.has(modelId)).length;
  const selectedRuntimeEstimateSeconds = useMemo(
    () => selectedModels.reduce((sum, modelId) => sum + (runtimeEstimateMap.get(modelId)?.estimatedSeconds ?? 0), 0),
    [runtimeEstimateMap, selectedModels]
  );
  const runLimitMessage = useMemo(() => {
    if (targetColumns.length > maxTargetColumns) return `一次最多选择 ${maxTargetColumns} 个目标列，请分批运行宽表数据。`;
    if (modelRunCount > maxModelRuns) return `一次最多运行 ${maxModelRuns} 个目标-模型组合，当前是 ${modelRunCount} 个。`;
    if (heavyModelRunCount > maxHeavyModelRuns) return `Prophet / TimesFM 属于重模型，一次最多运行 ${maxHeavyModelRuns} 个重模型组合，当前是 ${heavyModelRunCount} 个。`;
    return null;
  }, [heavyModelRunCount, modelRunCount, targetColumns.length]);
  const canRunExperiment = Boolean(
    targetColumns.length &&
      selectedModels.length &&
      horizonRange.compatible &&
      horizon >= horizonRange.min &&
      horizon <= horizonRange.max &&
      (!selectedFeatureAwareModels.length || featureConfigHasAnyEnabled) &&
      testSize >= 1 &&
      !runLimitMessage &&
      !loading
  );

  const stepCompletion = [
    Boolean(dataMode),
    Boolean(timeColumn && targetColumns.length),
    Boolean(selectedModels.length),
    Boolean(horizonRange.compatible && horizon >= horizonRange.min && horizon <= horizonRange.max && testSize >= 1 && !runLimitMessage),
    Boolean(forecastResult)
  ];
  const completedStepIndexes = stepCompletion.map((done, index) => (done ? index : -1)).filter((index) => index >= 0);
  const nextIncompleteStep = stepCompletion.findIndex((done) => !done);
  const activeStepIndex = loading ? 4 : nextIncompleteStep === -1 ? 4 : nextIncompleteStep;
  const elapsedSeconds = runStartedAt === null ? 0 : Math.max(0, Math.floor((progressNow - runStartedAt) / 1000));

  function updateModelParameter(modelId: string, key: string, value: ModelParameterValue) {
    setModelParameters((current) => ({
      ...current,
      [modelId]: {
        ...(modelParameterDefaults[modelId] ?? {}),
        ...(current[modelId] ?? {}),
        [key]: value
      }
    }));
  }

  function persistLeakageReminder(value: boolean) {
    if (typeof window === "undefined") return;
    const key = leakageReminderStorageKey(currentUser?.userId);
    if (value) {
      window.localStorage.setItem(key, "1");
    } else {
      window.localStorage.removeItem(key);
    }
    setSuppressLeakageWarning(value);
  }

  function updateCovariateConfig(column: string, patch: Partial<CovariateConfig>) {
    const current = normalizeCovariateConfig(column, covariateConfigs[column]);
    const next = normalizeCovariateConfig(column, { ...current, ...patch });
    const appliesLeakageMode = next.type === "static" && next.backtestStrategy === "use_test_values";
    if (appliesLeakageMode && !suppressLeakageWarning) {
      setLeakageDialogColumn(column);
      return;
    }
    setCovariateConfigs((configs) => ({ ...configs, [column]: next }));
  }

  async function submit() {
    if (!upload || !selectedSheet) return;
    if (runLimitMessage) {
      setError(runLimitMessage);
      return;
    }
    const startedAt = Date.now();
    const runId = createRunId();
    setRunStartedAt(startedAt);
    setProgressNow(startedAt);
    setRunProgress(null);
    setActiveRunId(runId);
    setRuntimeDetail(null);
    setLoading(true);
    setError(null);
    const stopProgress = subscribeForecastProgress(runId, setRunProgress);
    try {
      const request: ForecastRunRequest = {
        runId,
        uploadId: upload.uploadId,
        sheetName: selectedSheet.sheetName,
        dataMode,
        timeColumn,
        targetColumns,
        covariateColumns,
        aggregation: { enabled: dataMode === "raw", method: aggregationMethod },
        frequency: "auto",
        horizon,
        testSize,
        selectedModels,
        modelParameters: Object.fromEntries(selectedModels.map((modelId) => [modelId, modelParameters[modelId] ?? {}])),
        featureConfig,
        cleaningConfig: {
          preset: cleaningPreset,
          sortByTime: true,
          invalidTimeStrategy,
          trimStrings: true,
          normalizeThousandsSeparators: true,
          missingValueStrategy,
          interpolationLimit,
          fillMissingTimeSteps,
          duplicateTimeStrategy,
          outlierStrategy,
          outlierIqrMultiplier,
          hampelWindow,
          hampelSigma
        },
        covariateConfigs: covariateColumns.map((column) => normalizeCovariateConfig(column, covariateConfigs[column])),
        holidayConfig,
        missingValueStrategy,
        fillMissingTimeSteps,
        duplicateTimeStrategy,
        outlierStrategy,
        outlierIqrMultiplier,
        trimStrings: true,
        runProfile,
        parameterStrategy,
        randomSeed
      };
      const response = await runForecast(request);
      setForecastResult(response);
      if (rerunDraft) setRerunDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "实验运行失败，请检查字段、模型或测试集长度。");
    } finally {
      stopProgress();
      setLoading(false);
      setRunStartedAt(null);
    }
  }

  async function submitFinalForecast() {
    if (!forecastResult || !finalModelId) return;
    const startedAt = Date.now();
    const runId = createRunId();
    setRunStartedAt(startedAt);
    setProgressNow(startedAt);
    setRunProgress(null);
    setActiveRunId(runId);
    setRuntimeDetail(null);
    setLoading(true);
    setError(null);
    const stopProgress = subscribeForecastProgress(runId, setRunProgress);
    try {
      setFinalForecast(await runFinalForecast(forecastResult.experimentId, finalModelId, horizon, runId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "最终预测失败，请检查最终模型是否可用。");
    } finally {
      stopProgress();
      setLoading(false);
      setRunStartedAt(null);
    }
  }

  if (!upload || !selectedSheet) {
    return <EmptyState title="还没有可用数据" detail="请先上传文件并选择 Sheet，然后再配置预测实验。" />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="预测实验"
        title={forecastResult ? "分析驾驶舱" : "配置字段、模型和 Holdout 回测"}
        description={`文件：${upload.fileName} / Sheet：${selectedSheet.sheetName} / 计算设备：${device}`}
        action={
          <Link className={controls.secondaryButton} to="/upload">
            更换数据
          </Link>
        }
      />

      <ErrorBanner message={error} />
      <WorkbenchIdeaPanel
        disabled={!selectedSheet}
        targetColumn={targetColumns[0] ?? null}
        frequency={forecastResult?.detectedFrequency ?? runtimeDetail?.featurePipeline[0]?.detectedFrequency ?? null}
        availableColumns={selectedSheet.columns.map((column) => column.name)}
        horizon={horizon}
      />
      {rerunDraft ? (
        <SectionCard
          title="重新运行草稿"
          description={`来源实验 ${rerunDraft.experimentId}，配置 Hash：${rerunDraft.configHash.slice(0, 12)}...`}
          action={
            <button className={controls.secondaryButton} onClick={() => setRerunDraft(null)}>
              清除草稿
            </button>
          }
        >
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl bg-slate-50 p-3 text-xs leading-6 text-slate-600 dark:bg-[#151b2e] dark:text-slate-300">
              目标源文件：{rerunDraft.manifest.data.fileName}
              <br />
              源文件 SHA256：{rerunDraft.sourceFileSha256}
            </div>
            <div className={`rounded-2xl border p-3 text-xs leading-6 ${
              rerunDraft.fileMatch.exactMatch === false
                ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-100"
                : "border-slate-200 bg-white text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300"
            }`}>
              当前上传文件：{upload.fileName}
              <br />
              当前 SHA256：{upload.fileSha256}
              <br />
              校验结果：{rerunDraft.fileMatch.exactMatch ? "完全一致" : rerunDraft.fileMatch.exactMatch === false ? "不完全一致" : "等待重新上传比对"}
            </div>
          </div>
          {rerunDraft.fileMatch.warnings.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {rerunDraft.fileMatch.warnings.map((warning) => <Badge key={warning} tone="warn">{warning}</Badge>)}
            </div>
          ) : null}
        </SectionCard>
      ) : null}
      {loading ? (
        <div className="space-y-5">
          <RunningProgress
            finalForecastMode={Boolean(forecastResult)}
            selectedModelIds={selectedModels}
            models={models}
            finalModelId={finalModelId}
            elapsedSeconds={elapsedSeconds}
            parameterStrategy={parameterStrategy}
            progress={runProgress}
            runtimeDetail={runtimeDetail}
          />
        </div>
      ) : null}

      {!forecastResult ? (
        <>
          <Stepper steps={steps} activeIndex={activeStepIndex} completedIndexes={loading ? [0, 1, 2, 3] : completedStepIndexes} />
          <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard title="Step 1-2：数据模式与字段" description="先确认这是已聚合时间序列还是原始明细，再选择时间列和预测目标。">
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">数据类型</span>
                  <select className={controls.input} value={dataMode} onChange={(event) => setDataMode(event.target.value as "aggregated" | "raw")}>
                    <option value="aggregated">已聚合时间序列</option>
                    <option value="raw">原始明细数据，需要按时间聚合</option>
                  </select>
                </label>
                <label className="space-y-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">时间列</span>
                  <select className={controls.input} value={timeColumn} onChange={(event) => setTimeColumn(event.target.value)}>
                    {orderedColumns.map((column) => (
                      <option key={column.name} value={column.name}>
                        {column.name} ({column.inferredType})
                      </option>
                    ))}
                  </select>
                </label>
                {dataMode === "raw" ? (
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">聚合方式</span>
                    <select className={controls.input} value={aggregationMethod} onChange={(event) => setAggregationMethod(event.target.value as ForecastRunRequest["aggregation"]["method"])}>
                      {["sum", "mean", "count", "max", "min"].map((method) => (
                        <option key={method} value={method}>
                          {method}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <div className="space-y-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">预测目标列</span>
                  <div className="max-h-44 overflow-auto rounded-2xl border border-slate-200 p-2 dark:border-white/10">
                    {orderedColumns.map((column) => {
                      const selected = targetColumns.includes(column.name);
                      const targetLimitReached = !selected && targetColumns.length >= maxTargetColumns;
                      return (
                      <label key={column.name} className={`flex items-center gap-2 rounded-xl px-2 py-2 text-sm hover:bg-slate-50 dark:hover:bg-white/5 ${targetLimitReached ? "opacity-50" : ""}`}>
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={targetLimitReached}
                          onChange={(event) =>
                            setTargetColumns((current) => {
                              if (!event.target.checked) return current.filter((item) => item !== column.name);
                              if (current.includes(column.name) || current.length >= maxTargetColumns) return current;
                              return [...current, column.name];
                            })
                          }
                        />
                        <span className="min-w-0 flex-1 truncate">{column.name}</span>
                        <Badge tone={column.inferredType === "number" ? "good" : column.inferredType === "datetime" ? "info" : "neutral"}>{column.inferredType}</Badge>
                      </label>
                    );
                    })}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">已选择 {targetColumns.length} / {maxTargetColumns} 个目标列。</p>
                  {targetColumns.length > 1 ? <p className="text-xs text-amber-600 dark:text-amber-300">多目标会按目标列分别运行单变量预测。</p> : null}
                </div>
                <div className="space-y-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">协变量列（可选）</span>
                  <div className="max-h-44 overflow-auto rounded-2xl border border-slate-200 p-2 dark:border-white/10">
                    {availableCovariateColumns.length ? availableCovariateColumns.map((column) => {
                      const selected = covariateColumns.includes(column.name);
                      return (
                        <label key={column.name} className="flex items-center gap-2 rounded-xl px-2 py-2 text-sm hover:bg-slate-50 dark:hover:bg-white/5">
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={(event) => {
                              setCovariateColumns((current) => {
                                if (!event.target.checked) return current.filter((item) => item !== column.name);
                                return current.includes(column.name) ? current : [...current, column.name];
                              });
                              if (event.target.checked) {
                                setCovariateConfigs((current) => current[column.name] ? current : {
                                  ...current,
                                  [column.name]: covariateDefaults(column.name)
                                });
                              }
                            }}
                          />
                          <span className="min-w-0 flex-1 truncate">{column.name}</span>
                          <Badge tone={column.inferredType === "boolean" ? "info" : "good"}>{column.inferredType}</Badge>
                        </label>
                      );
                    }) : (
                      <div className="px-2 py-3 text-sm text-slate-500 dark:text-slate-400">当前没有可选协变量。协变量只支持数值或布尔列，且不能与时间列、目标列重复。</div>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">已选择 {covariateColumns.length} 个协变量。当前同一时间桶内多行协变量会按均值对齐。</p>
                </div>
              </div>
              <div className="mt-5 space-y-5 border-t border-slate-200 pt-5 dark:border-white/10">
                <div>
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">基础数据清洁</div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">先选择预设，再按需要调整时间、缺失值、重复值、异常值和协变量策略。</p>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  {([
                    ["conservative", "保守", "删除缺失值，不补时间缺口，仅检测异常"],
                    ["standard", "标准", "时间插值最多 3 点，仅检测异常"],
                    ["strict", "严格", "时间插值最多 7 点，Hampel 替换异常"]
                  ] as const).map(([id, label, detail]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => {
                        const preset = cleaningPresets[id];
                        setCleaningPreset(id);
                        setMissingValueStrategy(preset.missingValueStrategy ?? "drop");
                        setInterpolationLimit(preset.interpolationLimit ?? null);
                        setFillMissingTimeSteps(Boolean(preset.fillMissingTimeSteps));
                        setOutlierStrategy(preset.outlierStrategy ?? "none");
                      }}
                      className={`rounded-xl border p-3 text-left transition ${cleaningPreset === id ? "border-indigo-400 bg-indigo-50 ring-1 ring-indigo-300 dark:bg-indigo-400/10" : "border-slate-200 dark:border-white/10"}`}
                    >
                      <div className="font-semibold text-slate-900 dark:text-white">{label}</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{detail}</div>
                    </button>
                  ))}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">缺失值处理</span>
                    <select className={controls.input} value={missingValueStrategy} onChange={(event) => { setCleaningPreset("custom"); setMissingValueStrategy(event.target.value as ForecastRunRequest["missingValueStrategy"]); }}>
                      <option value="drop">删除缺失值</option><option value="zero">填充为 0</option><option value="ffill">前向填充</option><option value="bfill">后向填充</option><option value="interpolate">线性插值</option><option value="time">按时间插值</option><option value="median">中位数填充</option>
                    </select>
                  </label>
                  {dataMode === "aggregated" ? (
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-200">重复时间处理</span>
                      <select className={controls.input} value={duplicateTimeStrategy} onChange={(event) => { setCleaningPreset("custom"); setDuplicateTimeStrategy(event.target.value as ForecastRunRequest["duplicateTimeStrategy"]); }}>
                        <option value="mean">取平均值</option><option value="sum">求和</option><option value="first">保留第一条</option><option value="last">保留最后一条</option>
                      </select>
                    </label>
                  ) : null}
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">异常值处理</span>
                    <select className={controls.input} value={outlierStrategy} onChange={(event) => { setCleaningPreset("custom"); setOutlierStrategy(event.target.value as ForecastRunRequest["outlierStrategy"]); }}>
                      <option value="none">仅检测，不修改</option><option value="clip_iqr">按 IQR 边界截尾</option><option value="hampel">Hampel 中位数替换</option>
                    </select>
                  </label>
                  <label className="flex items-center gap-3 text-sm text-slate-700 dark:text-slate-200">
                    <input type="checkbox" checked={fillMissingTimeSteps} onChange={(event) => { setCleaningPreset("custom"); setFillMissingTimeSteps(event.target.checked); }} />补齐缺失时间点
                  </label>
                </div>
                <button type="button" className={controls.secondaryButton} onClick={() => setAdvancedCleaning((value) => !value)} aria-expanded={advancedCleaning}>
                  {advancedCleaning ? "收起高级清洗" : "展开高级清洗"}
                </button>
                {advancedCleaning ? (
                  <div className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-2 xl:grid-cols-4 dark:border-white/10 dark:bg-[#0b1020]">
                    <label className="space-y-2"><span className="text-sm">无效时间</span><select className={controls.input} value={invalidTimeStrategy} onChange={(event) => { setCleaningPreset("custom"); setInvalidTimeStrategy(event.target.value as CleaningConfig["invalidTimeStrategy"]); }}><option value="drop">删除并告警</option><option value="error">立即报错</option></select></label>
                    <label className="space-y-2"><span className="text-sm">最大连续插值点</span><input className={controls.input} type="number" min={1} max={365} value={interpolationLimit ?? ""} onChange={(event) => { setCleaningPreset("custom"); setInterpolationLimit(event.target.value ? Number(event.target.value) : null); }} /></label>
                    {outlierStrategy === "clip_iqr" ? <label className="space-y-2"><span className="text-sm">IQR 倍数</span><input className={controls.input} type="number" min={1} max={5} step={0.1} value={outlierIqrMultiplier} onChange={(event) => setOutlierIqrMultiplier(Number(event.target.value))} /></label> : null}
                    {outlierStrategy === "hampel" ? <><label className="space-y-2"><span className="text-sm">Hampel 窗口</span><input className={controls.input} type="number" min={3} max={101} step={2} value={hampelWindow} onChange={(event) => setHampelWindow(Number(event.target.value))} /></label><label className="space-y-2"><span className="text-sm">Hampel 阈值</span><input className={controls.input} type="number" min={1} max={10} step={0.5} value={hampelSigma} onChange={(event) => setHampelSigma(Number(event.target.value))} /></label></> : null}
                    <div className="rounded-lg bg-white p-3 text-xs leading-6 text-slate-500 dark:bg-[#151b2e] dark:text-slate-300">固定启用：按时间排序、修剪首尾空白、规范化千分位。</div>
                  </div>
                ) : null}

                <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="font-semibold text-slate-900 dark:text-white">协变量处理方式</div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">主流程只支持 known_future / static。static 的最终预测永远使用 repeat last known；backtest 可选 repeat last known、historical mean 或 use test values。</p>
                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    {covariateColumns.map((column) => {
                      const config = normalizeCovariateConfig(column, covariateConfigs[column]);
                      return (
                        <div key={column} className="rounded-xl bg-slate-50 p-3 dark:bg-[#0b1020]">
                          <div className="flex items-center justify-between gap-3">
                            <div className="font-medium text-slate-900 dark:text-white">{column}</div>
                            <Badge tone={config.type === "known_future" ? "info" : config.backtestStrategy === "use_test_values" ? "warn" : "neutral"}>
                              {config.type === "known_future" ? "Known Future" : "Static"}
                            </Badge>
                          </div>
                          <div className="mt-3 grid gap-3 sm:grid-cols-2">
                            <label className="space-y-1">
                              <span className="text-xs text-slate-500">类型</span>
                              <select className={controls.input} value={config.type} onChange={(event) => updateCovariateConfig(column, { type: event.target.value as CovariateConfig["type"] })}>
                                <option value="static">静态</option>
                                <option value="known_future">未来已知</option>
                              </select>
                            </label>
                            <label className="space-y-1">
                              <span className="text-xs text-slate-500">缺失值</span>
                              <select className={controls.input} value={config.missingValueStrategy} onChange={(event) => updateCovariateConfig(column, { missingValueStrategy: event.target.value as CovariateConfig["missingValueStrategy"] })}>
                                <option value="ffill">前向填充</option>
                                <option value="bfill">后向填充</option>
                                <option value="interpolate">线性插值</option>
                                <option value="time">按时间插值</option>
                                <option value="median">中位数</option>
                                <option value="zero">零值</option>
                              </select>
                            </label>
                            <label className="space-y-1 sm:col-span-2">
                              <span className="text-xs text-slate-500">Backtest Strategy</span>
                              <select
                                className={controls.input}
                                value={config.type === "known_future" ? "use_test_timeline" : config.backtestStrategy}
                                onChange={(event) => updateCovariateConfig(column, { backtestStrategy: event.target.value as CovariateConfig["backtestStrategy"] })}
                                disabled={config.type === "known_future"}
                              >
                                {config.type === "known_future" ? (
                                  <option value="use_test_timeline">Use Test Timeline Values</option>
                                ) : (
                                  <>
                                    <option value="repeat_last_known">Repeat Last Known</option>
                                    <option value="historical_mean">Historical Mean</option>
                                    <option value="use_test_values">Use Test Values（有泄漏风险）</option>
                                  </>
                                )}
                              </select>
                            </label>
                          </div>
                          <div className="mt-3 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs leading-6 text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300">
                            Forecast：{config.type === "known_future" ? "Generated by Calendar / Use Future Timeline" : "Repeat Last Known"}
                            <br />
                            Leakage Risk：{config.type === "known_future" ? "无" : config.backtestStrategy === "use_test_values" ? "高" : "无"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-semibold text-slate-900 dark:text-white">节假日生成器</div><div className="mt-1 text-xs text-slate-500">默认中国法定节假日，可切换国家和地区。</div></div><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={holidayConfig.enabled} onChange={(event) => setHolidayConfig((current) => ({ ...current, enabled: event.target.checked }))} />启用</label></div>
                  {holidayConfig.enabled ? <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <label className="space-y-1"><span className="text-xs text-slate-500">国家/地区</span><select className={controls.input} value={holidayConfig.countryCode} onChange={(event) => setHolidayConfig((current) => ({ ...current, countryCode: event.target.value, subdivision: null }))}>{(holidayCatalog?.countries ?? [{ code: "CN", name: "中国", subdivisions: [] }]).map((country) => <option key={country.code} value={country.code}>{country.name} ({country.code})</option>)}</select></label>
                    <label className="space-y-1"><span className="text-xs text-slate-500">行政区</span><select className={controls.input} value={holidayConfig.subdivision ?? ""} onChange={(event) => setHolidayConfig((current) => ({ ...current, subdivision: event.target.value || null }))}><option value="">全国</option>{(holidayCatalog?.countries.find((country) => country.code === holidayConfig.countryCode)?.subdivisions ?? []).map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
                    <label className="space-y-1"><span className="text-xs text-slate-500">节日前后窗口</span><input className={controls.input} type="number" min={0} max={30} value={holidayConfig.windowDays} onChange={(event) => setHolidayConfig((current) => ({ ...current, windowDays: Number(event.target.value) }))} /></label>
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={holidayConfig.observed} onChange={(event) => setHolidayConfig((current) => ({ ...current, observed: event.target.checked }))} />包含调休/补休日历</label>
                  </div> : null}
                </div>
              </div>            </SectionCard>

            <SectionCard
              title="Step 3-5：模型与回测"
              description={`模型按当前数据规模和主机内存压力排序。主机：${device.toUpperCase()}，可用 RAM：${formatMemory(deviceInfo?.memoryAvailableMb)}，总 RAM：${formatMemory(deviceInfo?.memoryTotalMb)}。`}
            >
              <div className="grid gap-4">
                <div className="grid gap-3 lg:grid-cols-3">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">运行模式</span>
                    <select className={controls.input} value={runProfile} onChange={(event) => setRunProfile(event.target.value as ForecastRunRequest["runProfile"])}>
                      <option value="fast">快速</option>
                      <option value="balanced">均衡</option>
                      <option value="accurate">精确</option>
                    </select>
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">参数策略</span>
                    <select className={controls.input} value={parameterStrategy} onChange={(event) => setParameterStrategy(event.target.value as ForecastRunRequest["parameterStrategy"])}>
                      <option value="default">默认参数</option>
                      <option value="auto">自动优化</option>
                    </select>
                  </label>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300">
                    随机种子：{randomSeed}
                    <br />
                    {parameterStrategy === "auto" ? "自动优化会按运行模式控制候选数量和时间预算。" : "默认参数会直接使用高级设置中的模型参数。"}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">featureConfig</div>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">当前只会被支持特征工程的模型消费：XGBoost、LightGBM、Random Forest。</p>
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      生效模型：{selectedFeatureAwareModels.length ? selectedFeatureAwareModels.map((model) => model.name).join(" / ") : "当前未选中"}
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                    {[
                      ["lagFeatures", "Lag 特征", "lag_1 / lag_7 等历史滞后值"],
                      ["rollingFeatures", "滚动统计", "rolling mean / std"],
                      ["calendarFeatures", "日历/趋势", "time index、weekday、month"],
                      ["holidayFeatures", "节假日特征", "国家日历、节日窗口与相邻天数"],
                      ["covariates", "用户协变量", "使用左侧勾选的协变量列"]
                    ].map(([key, label, description]) => (
                      <label key={key} className="rounded-2xl border border-slate-200 p-3 text-sm dark:border-white/10">
                        <div className="flex items-center gap-3">
                          <input
                            type="checkbox"
                            checked={featureConfig[key as keyof FeatureConfig]}
                            onChange={(event) => setFeatureConfig((current) => ({ ...current, [key]: event.target.checked }))}
                          />
                          <span className="font-medium text-slate-800 dark:text-slate-100">{label}</span>
                        </div>
                        <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</div>
                      </label>
                    ))}
                  </div>
                  {!featureConfigHasAnyEnabled && selectedFeatureAwareModels.length ? (
                    <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                      当前已经选中了会消费 featureConfig 的模型，请至少保留一种特征族，否则这些模型没有可用输入。
                    </div>
                  ) : null}
                  {covariateColumns.length && !featureConfig.covariates ? (
                    <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">你已经选中了 {covariateColumns.length} 个协变量，但“用户协变量”开关当前关闭，运行时不会使用它们。</div>
                  ) : null}
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">预测步长</span>
                    <span className="block text-xs text-slate-500 dark:text-slate-400">未来预测点数</span>
                    <input
                      className={controls.input}
                      type="number"
                      min={horizonRange.min}
                      max={horizonRange.max}
                      value={horizon}
                      onChange={(event) => {
                        const value = Number(event.target.value);
                        setHorizon(value);
                        setTestSize(value);
                      }}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">测试集长度</span>
                    <span className="block text-xs text-slate-500 dark:text-slate-400">留出评估点数</span>
                    <input className={controls.input} type="number" min={1} value={testSize} onChange={(event) => setTestSize(Number(event.target.value))} />
                  </label>
                </div>
                <div className="rounded-2xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-[#151b2e] dark:text-slate-300">
                  共同步长：{horizonRange.min} ~ {horizonRange.max}
                  {!horizonRange.compatible ? <span className="ml-2 text-red-600 dark:text-red-300">所选模型步长范围不兼容。</span> : null}
                </div>
                <div className="rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-900 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-50">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-cyan-700/80 dark:text-cyan-100/70">Runtime Estimator</div>
                      <div className="mt-1 font-semibold">
                        当前已选模型预计总时长：{selectedModels.length ? formatCompactDuration(selectedRuntimeEstimateSeconds) : "请选择模型"}
                      </div>
                    </div>
                    <Badge tone="info">{runtimeEstimates.length ? `已估算 ${runtimeEstimates.length} 个模型` : "等待估算"}</Badge>
                  </div>
                  <div className="mt-2 text-xs leading-5 text-cyan-800/90 dark:text-cyan-100/80">
                    估算基于历史实验运行时长学习，并结合当前行数、协变量、featureConfig、运行模式与自动优化策略动态调整。
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-3 text-xs text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300">
                  {[
                    ["green", "无压力"],
                    ["yellow", "有压力"],
                    ["red", "高压力"],
                    ["gray", "无法运行"]
                  ].map(([level, label]) => (
                    <span key={level} className="inline-flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full shadow-lg ${resourceToneClass[level as ResourceLevel]}`} />
                      {label}
                    </span>
                  ))}
                  <span className="text-slate-400 dark:text-slate-500">估算随文件大小、行列数、目标列和步长动态变化。</span>
                </div>
                <div className={`rounded-2xl border p-3 text-sm ${runLimitMessage ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100" : "border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300"}`}>
                  本次计划运行 {modelRunCount} 个目标-模型组合，重模型组合 {heavyModelRunCount} 个。
                  <span className="ml-2 text-xs opacity-75">上限：组合 {maxModelRuns}，重模型 {maxHeavyModelRuns}。</span>
                  {runLimitMessage ? <div className="mt-2 text-xs font-semibold">{runLimitMessage}</div> : null}
                </div>
                <div className="grid max-h-[520px] gap-3 overflow-auto pr-1 md:grid-cols-2">
                  {sortedModels.map((model) => (
                    <ModelCard
                      key={model.id}
                      model={model}
                      resource={resourceAssessments.get(model.id) ?? assessModelResource({ model, deviceInfo, upload, sheet: selectedSheet, dataMode, targetColumns, horizon, testSize })}
                      runtimeEstimate={runtimeEstimateMap.get(model.id)}
                      selected={selectedModels.includes(model.id)}
                      parameters={modelParameters[model.id] ?? modelParameterDefaults[model.id] ?? {}}
                      onChange={(checked) => setSelectedModels((current) => (checked ? (current.includes(model.id) ? current : [...current, model.id]) : current.filter((item) => item !== model.id)))}
                      onParameterChange={(key, value) => updateModelParameter(model.id, key, value)}
                    />
                  ))}
                </div>
                <button className={controls.primaryButton} disabled={!canRunExperiment} onClick={() => void submit()}>
                  运行 Holdout（留出测试集）回测
                </button>
              </div>
            </SectionCard>
          </div>
        </>
      ) : (
        <ResultsDashboard
          result={forecastResult}
          finalForecast={finalForecast}
          finalModelId={finalModelId}
          setFinalModelId={setFinalModelId}
          submitFinalForecast={() => void submitFinalForecast()}
          chartModelIds={chartModelIds}
          setChartModelIds={setChartModelIds}
          metric={metric}
          setMetric={setMetric}
        />
      )}

      {leakageDialogColumn ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <button type="button" className="absolute inset-0 bg-slate-950/60" onClick={() => { setLeakageDialogColumn(null); setLeakageDialogRemember(false); }} />
          <div className="relative w-full max-w-2xl rounded-3xl border border-amber-200 bg-white p-6 shadow-2xl dark:border-amber-400/20 dark:bg-[#151b2e]">
            <div className="text-lg font-semibold text-slate-950 dark:text-white">回测泄漏风险提示</div>
            <div className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
              你正在把 <span className="font-semibold">{leakageDialogColumn}</span> 设为 <span className="font-semibold">use_test_values</span>。
              该策略会在回归测试中使用测试集真实协变量值，可能造成未来信息泄漏，使回测指标偏乐观。仅建议用于 Academic Benchmark 或未来协变量确实已知的场景。
            </div>
            <label className="mt-4 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
              <input type="checkbox" checked={leakageDialogRemember} onChange={(event) => setLeakageDialogRemember(event.target.checked)} />
              不再提醒（按当前用户隔离保存）
            </label>
            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                className={controls.secondaryButton}
                onClick={() => {
                  setLeakageDialogColumn(null);
                  setLeakageDialogRemember(false);
                }}
              >
                取消
              </button>
              <button
                type="button"
                className={controls.primaryButton}
                onClick={() => {
                  if (!leakageDialogColumn) return;
                  if (leakageDialogRemember) persistLeakageReminder(true);
                  setCovariateConfigs((current) => ({
                    ...current,
                    [leakageDialogColumn]: normalizeCovariateConfig(leakageDialogColumn, {
                      ...current[leakageDialogColumn],
                      backtestStrategy: "use_test_values"
                    })
                  }));
                  setLeakageDialogColumn(null);
                  setLeakageDialogRemember(false);
                }}
              >
                继续并启用
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
