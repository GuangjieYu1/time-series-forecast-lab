import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Link } from "react-router-dom";
import { createRunId, fetchDeviceInfo, fetchModels, runFinalForecast, runForecast, subscribeForecastProgress } from "../../shared/api/client";
import { DataTable } from "../../shared/components/Table";
import { EmptyState, ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, Stepper, surface, Tabs } from "../../shared/components/Ui";
import { zhCN } from "../../shared/i18n/zhCN";
import type { DeviceInfo, ForecastProgress, ForecastRunRequest, ForecastRunResponse, ModelCapability, RankedModel, SheetPreview, UploadPreviewResponse } from "../../shared/types/api";
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

const modelDefaults = ["naive", "seasonal_naive", "moving_average", "arima", "ets", "prophet", "xgboost", "lightgbm", "random_forest"];
const steps = ["选择数据模式", "选择字段", "选择模型", "设置回测", "运行实验"];
const maxTargetColumns = 8;
const maxModelRuns = 32;
const maxHeavyModelRuns = 4;
const heavyModelIds = new Set(["prophet", "timesfm"]);

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
  prophet: { intervalWidth: 0.8, dailySeasonality: "auto", weeklySeasonality: "auto", yearlySeasonality: "auto" },
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

type ResultTab = "overview" | "residual" | "metrics" | "distribution" | "final" | "report";

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

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
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
    return { level: "red", label: "高压力", reason: "当前主机未检测到 GPU", minRamMb, dataRamMb, loadRank: profile.loadRank };
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
  progress
}: {
  finalForecastMode?: boolean;
  selectedModelIds?: string[];
  models?: ModelCapability[];
  finalModelId?: string;
  elapsedSeconds?: number;
  progress: ForecastProgress | null;
}) {
  const items = finalForecastMode
    ? ["读取完整历史数据", "重新训练最终模型", "生成未来预测", "更新预测图表"]
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
    fitting: { label: "拟合中", tone: "info" },
    predicting: { label: "预测中", tone: "info" },
    scoring: { label: "计算指标", tone: "warn" },
    success: { label: "已完成", tone: "good" },
    failed: { label: "失败", tone: "bad" }
  } as const;
  const progressRows = progress?.models.length
    ? progress.models.map((row) => ({
        ...row,
        id: row.modelId,
        name: row.modelName,
        family: modelMap.get(row.modelId)?.modelFamily || modelMap.get(row.modelId)?.category || "模型",
        requiresGpu: Boolean(modelMap.get(row.modelId)?.requiresGpu),
        displayStatus: statusMeta[row.status]
      }))
    : runningModels.map((model) => ({
        ...model,
        targetColumn: "",
        percent: 0,
        message: "等待后端接收任务。",
        fitSeconds: null,
        predictSeconds: null,
        error: null,
        displayStatus: statusMeta.queued
      }));
  const overallProgress = progress?.overallPercent ?? 1;
  const phaseIndex = (() => {
    const phase = progress?.phase ?? "preparing";
    if (phase.startsWith("model_") || phase === "fitting" || phase === "predicting") return 2;
    if (phase === "ranking" || phase === "saving" || phase === "completed") return 3;
    if (phase === "parsing" || phase === "profiling" || phase === "building_series") return 1;
    return 0;
  })();

  return (
    <SectionCard
      title={finalForecastMode ? "正在运行最终预测" : "正在运行预测实验"}
      description={finalForecastMode ? "后端正在用完整历史重新拟合最终模型并生成预测。" : "进度来自后端真实阶段事件；模型库不提供内部迭代百分比时，展示拟合、预测和指标计算阶段。"}
      className="overflow-hidden"
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-2xl font-semibold text-slate-950 dark:text-white">{overallProgress}%</div>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            已运行 {formatElapsed(elapsedSeconds)} · {progress?.message ?? "正在连接后端进度流。"}
          </div>
        </div>
        <Badge tone={progress?.status === "failed" ? "bad" : progress?.status === "completed" ? "good" : "info"}>
          {progress ? `${progress.completedModels}/${progress.totalModels} 个模型完成` : finalForecastMode ? "最终预测" : `${runningModels.length} 个模型回测`}
        </Badge>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700"
          style={{ width: `${overallProgress}%` }}
        />
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-4">
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
          {progressRows.map((model) => (
            <div key={`${model.targetColumn}:${model.id}`} className="rounded-2xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-[#151b2e]">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-950 dark:text-white">{model.name}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {model.family}{model.targetColumn ? ` / ${model.targetColumn}` : ""}{model.requiresGpu ? " / 建议 GPU" : ""}
                  </div>
                </div>
                <Badge tone={model.displayStatus.tone}>{model.displayStatus.label}</Badge>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all duration-500" style={{ width: `${model.percent}%` }} />
              </div>
              <div className="mt-2 flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400 sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0 break-words">{model.percent}% · {model.message}</span>
                <span className="shrink-0">
                  {model.fitSeconds !== null ? `拟合 ${model.fitSeconds.toFixed(2)}s` : ""}
                  {model.predictSeconds !== null ? ` / 预测 ${model.predictSeconds.toFixed(2)}s` : ""}
                </span>
              </div>
              {model.error ? <div className="mt-2 text-xs text-red-600 dark:text-red-300">{model.error}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </SectionCard>
  );
}

function Leaderboard({ rows, recommendedModelId }: { rows: RankedModel[]; recommendedModelId: string | null }) {
  return (
    <DataTable<RankedModel>
      data={rows}
      columns={[
        { header: "排名", cell: ({ row }) => row.original.rank ?? "-" },
        { header: "模型", cell: ({ row }) => row.original.modelName },
        { header: "MAE", cell: ({ row }) => metricText(row.original.metrics?.mae) },
        { header: "MSE", cell: ({ row }) => metricText(row.original.metrics?.mse) },
        { header: "RMSE", cell: ({ row }) => metricText(row.original.metrics?.rmse) },
        { header: "WAPE", cell: ({ row }) => metricText(row.original.metrics?.wape) },
        { header: "训练耗时", cell: ({ row }) => `${row.original.runtime.fitSeconds}s` },
        { header: "预测耗时", cell: ({ row }) => `${row.original.runtime.predictSeconds}s` },
        { header: "推荐", cell: ({ row }) => (row.original.modelId === recommendedModelId ? <Badge tone="good">推荐模型</Badge> : null) },
        { header: "状态", cell: ({ row }) => (row.original.status === "failed" ? <Badge tone="bad">{row.original.error ?? "运行失败"}</Badge> : <Badge tone="good">成功</Badge>) }
      ]}
    />
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
        if (field.type === "select") {
          return (
            <label key={field.key} className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
              <span className="font-medium">{field.label}</span>
              <select className={`${controls.input} h-9 text-xs`} value={String(value)} onChange={(event) => onChange(field.key, event.target.value)}>
                {(field.options ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        if (field.type === "boolean") {
          return (
            <label key={field.key} className="flex items-center gap-2 text-xs font-medium text-slate-600 dark:text-slate-300">
              <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(field.key, event.target.checked)} />
              {field.label}
            </label>
          );
        }
        return (
          <label key={field.key} className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
            <span className="font-medium">{field.label}</span>
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
  parameters,
  onChange,
  onParameterChange
}: {
  model: ModelCapability;
  selected: boolean;
  resource: ModelResourceAssessment;
  parameters: Record<string, ModelParameterValue>;
  onChange: (checked: boolean) => void;
  onParameterChange: (key: string, value: ModelParameterValue) => void;
}) {
  const runnable = isRunnableModel(model) && resource.level !== "gray";
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
          <label className={`inline-flex items-center gap-2 text-xs font-semibold ${runnable ? "cursor-pointer text-indigo-600 dark:text-indigo-200" : "cursor-not-allowed text-slate-400"}`}>
            <input type="checkbox" disabled={!runnable} checked={selected} onChange={(event) => onChange(event.target.checked)} />
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
  const [tab, setTab] = useState<ResultTab>("overview");
  const best = result.rankedModels.find((model) => model.rank === 1 && model.metrics);
  const successfulModels = result.rankedModels.filter((model) => model.status === "success");

  return (
    <section className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="目标列" value={result.targetColumn} hint="当前分析目标" tone="info" />
        <StatCard label="时间范围" value={result.diagnostics.timeStart ?? "-"} hint={result.diagnostics.timeEnd ?? "结束时间未知"} />
        <StatCard label="样本数" value={result.diagnostics.validRowCount} hint={`丢弃 ${result.diagnostics.droppedRowCount} 行`} />
        <StatCard label="推荐模型" value={result.recommendedModelId ?? "暂无"} hint="按 MAE 最低推荐" tone="good" />
        <StatCard label="最佳 MAE" value={metricText(best?.metrics?.mae)} hint="越低越好" tone="good" />
        <StatCard label="最佳 WAPE" value={metricText(best?.metrics?.wape)} hint="总绝对误差占比" tone="warn" />
      </div>

      <SectionCard title="数据清洁摘要" description="清洁只作用于本次实验构建的时间序列，不修改上传原文件。">
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
              <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">推荐原因：测试集 MAE 最低。失败模型已被保留在排行榜，但不参与推荐。</p>
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
              <div className="space-y-2">
                {successfulModels
                  .filter((model) => result.backtest.predictions[model.modelId])
                  .map((model) => (
                    <label key={model.modelId} className="flex items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-white/10">
                      <span>{model.modelName}</span>
                      <input
                        type="checkbox"
                        checked={chartModelIds.includes(model.modelId)}
                        onChange={(event) => setChartModelIds((current) => (event.target.checked ? [...current, model.modelId] : current.filter((modelId) => modelId !== model.modelId)))}
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
          { id: "overview", label: "预测对比" },
          { id: "residual", label: "残差分析" },
          { id: "metrics", label: "指标排名" },
          { id: "distribution", label: "误差分布" },
          { id: "final", label: "最终预测" },
          { id: "report", label: "AI 报告" }
        ]}
      />

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
            <Leaderboard rows={result.rankedModels} recommendedModelId={result.recommendedModelId} />
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

      {tab === "final" ? (
        <div className={surface.chartPanel}><FinalForecastChart finalForecast={finalForecast} /></div>
      ) : null}

      {tab === "report" ? <div id="ai-report"><ReportPanel experimentId={result.experimentId} /></div> : null}
    </section>
  );
}

export function ForecastPage() {
  const { upload, selectedSheet, forecastResult, finalForecast, setForecastResult, setFinalForecast } = useLabStore();
  const [models, setModels] = useState<ModelCapability[]>([]);
  const [device, setDevice] = useState("cpu");
  const [deviceInfo, setDeviceInfo] = useState<DeviceInfo | null>(null);
  const [dataMode, setDataMode] = useState<"aggregated" | "raw">("aggregated");
  const [timeColumn, setTimeColumn] = useState("");
  const [targetColumns, setTargetColumns] = useState<string[]>([]);
  const [aggregationMethod, setAggregationMethod] = useState<ForecastRunRequest["aggregation"]["method"]>("sum");
  const [missingValueStrategy, setMissingValueStrategy] = useState<ForecastRunRequest["missingValueStrategy"]>("drop");
  const [fillMissingTimeSteps, setFillMissingTimeSteps] = useState(true);
  const [duplicateTimeStrategy, setDuplicateTimeStrategy] = useState<ForecastRunRequest["duplicateTimeStrategy"]>("mean");
  const [outlierStrategy, setOutlierStrategy] = useState<ForecastRunRequest["outlierStrategy"]>("none");
  const [outlierIqrMultiplier, setOutlierIqrMultiplier] = useState(1.5);
  const [horizon, setHorizon] = useState(7);
  const [testSize, setTestSize] = useState(7);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [modelParameters, setModelParameters] = useState<Record<string, Record<string, ModelParameterValue>>>(modelParameterDefaults);
  const [metric, setMetric] = useState<"mae" | "mse" | "rmse" | "wape">("mae");
  const [finalModelId, setFinalModelId] = useState("");
  const [chartModelIds, setChartModelIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [progressNow, setProgressNow] = useState(Date.now());
  const [runProgress, setRunProgress] = useState<ForecastProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetchModels()
      .then((modelList) => {
        setModels(modelList);
        const runnableDefaults = modelList.filter((model) => modelDefaults.includes(model.id) && isRunnableModel(model)).map((model) => model.id);
        setSelectedModels(runnableDefaults);
      })
      .catch(() => setModels([]));
    void fetchDeviceInfo()
      .then((info) => {
        setDeviceInfo(info);
        setDevice(info.device);
      })
      .catch(() => {
        setDeviceInfo({ device: "cpu", memoryTotalMb: null, memoryAvailableMb: null });
        setDevice("cpu");
      });
  }, []);

  useEffect(() => {
    if (!selectedSheet) return;
    const firstTime = selectedSheet.columns.find((column) => column.inferredType === "datetime")?.name ?? selectedSheet.columns[0]?.name ?? "";
    const firstNumber = selectedSheet.columns.find((column) => column.inferredType === "number")?.name ?? selectedSheet.columns[1]?.name ?? "";
    setTimeColumn(firstTime);
    setTargetColumns(firstNumber ? [firstNumber] : []);
  }, [selectedSheet]);

  useEffect(() => {
    if (forecastResult?.recommendedModelId) {
      setFinalModelId(forecastResult.recommendedModelId);
      setChartModelIds(defaultVisibleModelIds(forecastResult));
    }
  }, [forecastResult]);

  useEffect(() => {
    if (!loading || runStartedAt === null) return;
    setProgressNow(Date.now());
    const timer = window.setInterval(() => setProgressNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [loading, runStartedAt]);

  const orderedColumns = useMemo(() => {
    if (!selectedSheet) return [];
    return [...selectedSheet.columns].sort((left, right) => {
      const score = (type: string) => (type === "datetime" ? 0 : type === "number" ? 1 : 2);
      return score(left.inferredType) - score(right.inferredType);
    });
  }, [selectedSheet]);

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

  useEffect(() => {
    const availableIds = new Set(models.filter((model) => resourceAssessments.get(model.id)?.level !== "gray").map((model) => model.id));
    setSelectedModels((current) => current.filter((modelId) => availableIds.has(modelId)));
  }, [models, resourceAssessments]);

  const horizonRange = useMemo(() => {
    const selected = models.filter((model) => selectedModels.includes(model.id));
    if (!selected.length) return { min: 1, max: 1, compatible: false };
    const min = Math.max(...selected.map((model) => model.minHorizon));
    const max = Math.min(...selected.map((model) => model.maxHorizon));
    return { min, max, compatible: min <= max };
  }, [models, selectedModels]);
  const modelRunCount = targetColumns.length * selectedModels.length;
  const heavyModelRunCount = targetColumns.length * selectedModels.filter((modelId) => heavyModelIds.has(modelId)).length;
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
        aggregation: { enabled: dataMode === "raw", method: aggregationMethod },
        frequency: "auto",
        horizon,
        testSize,
        selectedModels,
        modelParameters: Object.fromEntries(selectedModels.map((modelId) => [modelId, modelParameters[modelId] ?? {}])),
        missingValueStrategy,
        fillMissingTimeSteps,
        duplicateTimeStrategy,
        outlierStrategy,
        outlierIqrMultiplier,
        trimStrings: true
      };
      const response = await runForecast(request);
      setForecastResult(response);
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
      {loading ? (
        <RunningProgress
          finalForecastMode={Boolean(forecastResult)}
          selectedModelIds={selectedModels}
          models={models}
          finalModelId={finalModelId}
          elapsedSeconds={elapsedSeconds}
          progress={runProgress}
        />
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
              </div>
              <div className="mt-5 border-t border-slate-200 pt-5 dark:border-white/10">
                <div className="mb-3">
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">基础数据清洁</div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">先清理时间和目标值，再聚合、补齐时间缺口并检测异常值。</p>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">缺失值处理</span>
                    <select className={controls.input} value={missingValueStrategy} onChange={(event) => setMissingValueStrategy(event.target.value as ForecastRunRequest["missingValueStrategy"])}>
                      <option value="drop">删除缺失值（保守）</option>
                      <option value="interpolate">线性插值</option>
                      <option value="ffill">前向填充</option>
                      <option value="zero">填充为 0</option>
                    </select>
                  </label>
                  {dataMode === "aggregated" ? (
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-200">重复时间处理</span>
                      <select className={controls.input} value={duplicateTimeStrategy} onChange={(event) => setDuplicateTimeStrategy(event.target.value as ForecastRunRequest["duplicateTimeStrategy"])}>
                        <option value="mean">取平均值</option>
                        <option value="sum">求和</option>
                        <option value="first">保留第一条</option>
                        <option value="last">保留最后一条</option>
                      </select>
                    </label>
                  ) : null}
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">异常值处理</span>
                    <select className={controls.input} value={outlierStrategy} onChange={(event) => setOutlierStrategy(event.target.value as ForecastRunRequest["outlierStrategy"])}>
                      <option value="none">仅检测，不修改（推荐）</option>
                      <option value="clip_iqr">按 IQR 边界截尾</option>
                    </select>
                  </label>
                  {outlierStrategy === "clip_iqr" ? (
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-200">IQR 倍数</span>
                      <input className={controls.input} type="number" min={1} max={5} step={0.1} value={outlierIqrMultiplier} onChange={(event) => setOutlierIqrMultiplier(Number(event.target.value))} />
                    </label>
                  ) : null}
                  <label className="flex items-center gap-3 text-sm text-slate-700 dark:text-slate-200">
                    <input type="checkbox" checked={fillMissingTimeSteps} onChange={(event) => setFillMissingTimeSteps(event.target.checked)} />
                    补齐缺失时间点
                  </label>
                </div>
              </div>
            </SectionCard>

            <SectionCard
              title="Step 3-5：模型与回测"
              description={`模型按当前数据规模和主机内存压力排序。主机：${device.toUpperCase()}，可用 RAM：${formatMemory(deviceInfo?.memoryAvailableMb)}，总 RAM：${formatMemory(deviceInfo?.memoryTotalMb)}。`}
            >
              <div className="grid gap-4">
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
    </div>
  );
}
