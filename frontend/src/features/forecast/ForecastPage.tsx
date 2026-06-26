import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Link } from "react-router-dom";
import { fetchDeviceInfo, fetchModels, runFinalForecast, runForecast } from "../../shared/api/client";
import { DataTable } from "../../shared/components/Table";
import { EmptyState, ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, Stepper, surface, Tabs } from "../../shared/components/Ui";
import { zhCN } from "../../shared/i18n/zhCN";
import type { DeviceInfo, ForecastRunRequest, ForecastRunResponse, ModelCapability, RankedModel, SheetPreview, UploadPreviewResponse } from "../../shared/types/api";
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

const modelProgressWeights: Record<string, number> = {
  naive: 2,
  seasonal_naive: 3,
  moving_average: 2,
  arima: 8,
  ets: 7,
  prophet: 12,
  xgboost: 8,
  lightgbm: 8,
  random_forest: 7,
  timesfm: 24
};

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
  elapsedSeconds = 0
}: {
  finalForecastMode?: boolean;
  selectedModelIds?: string[];
  models?: ModelCapability[];
  finalModelId?: string;
  elapsedSeconds?: number;
}) {
  const items = finalForecastMode
    ? ["读取完整历史数据", "重新训练最终模型", "生成未来预测", "更新预测图表"]
    : ["校验字段配置", "构建时间序列", "运行模型回测", "计算残差指标"];
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
  const weights = runningModels.map((model) => modelProgressWeights[model.id] ?? 6);
  const totalWeight = Math.max(weights.reduce((sum, item) => sum + item, 0) + 8, 12);
  const overallProgress = Math.min(92, Math.max(10, Math.round((elapsedSeconds / totalWeight) * 82 + 10)));
  let accumulatedWeight = 0;
  const progressRows = runningModels.map((model, index) => {
    const weight = weights[index];
    const startAt = accumulatedWeight;
    accumulatedWeight += weight;
    const raw = elapsedSeconds <= startAt ? 6 : elapsedSeconds >= startAt + weight ? 88 : 14 + Math.round(((elapsedSeconds - startAt) / weight) * 70);
    const progress = Math.min(88, Math.max(6, raw));
    const status = progress < 12 ? "排队中" : progress >= 88 ? "等待结果" : "运行中";
    const tone: "neutral" | "good" | "warn" | "bad" | "info" = status === "运行中" ? "info" : status === "等待结果" ? "good" : "neutral";
    return { ...model, progress, status, tone };
  });

  return (
    <SectionCard
      title={finalForecastMode ? "正在运行最终预测" : "正在运行预测实验"}
      description={finalForecastMode ? "系统正在用最终模型预测未来时间点。" : "系统正在执行 holdout 回测；每个模型会单独展示估算进度，最终结果以后端返回为准。"}
      className="overflow-hidden"
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-2xl font-semibold text-slate-950 dark:text-white">{overallProgress}%</div>
          <div className="text-xs text-slate-500 dark:text-slate-400">已运行 {formatElapsed(elapsedSeconds)}</div>
        </div>
        <Badge tone="info">{finalForecastMode ? "最终预测" : `${runningModels.length} 个模型回测`}</Badge>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700"
          style={{ width: `${overallProgress}%` }}
        />
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-4">
        {items.map((item) => (
          <div key={item} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300">
            {item}
          </div>
        ))}
      </div>
      {progressRows.length ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {progressRows.map((model) => (
            <div key={model.id} className="rounded-2xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-[#151b2e]">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-950 dark:text-white">{model.name}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {model.family}{model.requiresGpu ? " / 建议 GPU" : ""}
                  </div>
                </div>
                <Badge tone={model.tone}>{model.status}</Badge>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all duration-700" style={{ width: `${model.progress}%` }} />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>{model.progress}%</span>
                <span>{model.id === "timesfm" ? "首次加载可能较慢" : "后端完成后确认"}</span>
              </div>
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

function ModelCard({
  model,
  selected,
  resource,
  onChange
}: {
  model: ModelCapability;
  selected: boolean;
  resource: ModelResourceAssessment;
  onChange: (checked: boolean) => void;
}) {
  const runnable = isRunnableModel(model) && resource.level !== "gray";
  return (
    <button
      type="button"
      disabled={!runnable}
      onClick={() => runnable && onChange(!selected)}
      className={`rounded-2xl border p-4 text-left transition ${
        selected
          ? "border-indigo-400 bg-indigo-50 shadow-sm dark:border-indigo-300/40 dark:bg-indigo-400/10"
          : "border-slate-200 bg-white hover:border-slate-300 dark:border-white/10 dark:bg-[#151b2e] dark:hover:border-white/20"
      } ${runnable ? "" : "opacity-60"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold text-slate-950 dark:text-white">
            <span className={`h-2.5 w-2.5 rounded-full shadow-lg ${resourceToneClass[resource.level]}`} />
            {model.name}
          </div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{model.modelFamily || model.category}</div>
        </div>
        <Badge tone={modelStatusTone(model)}>{modelStatusText(model)}</Badge>
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
    </button>
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
  const [horizon, setHorizon] = useState(7);
  const [testSize, setTestSize] = useState(7);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [metric, setMetric] = useState<"mae" | "mse" | "rmse" | "wape">("mae");
  const [finalModelId, setFinalModelId] = useState("");
  const [chartModelIds, setChartModelIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [progressNow, setProgressNow] = useState(Date.now());
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

  const stepCompletion = [
    Boolean(dataMode),
    Boolean(timeColumn && targetColumns.length),
    Boolean(selectedModels.length),
    Boolean(horizonRange.compatible && horizon >= horizonRange.min && horizon <= horizonRange.max && testSize >= 1),
    Boolean(forecastResult)
  ];
  const completedStepIndexes = stepCompletion.map((done, index) => (done ? index : -1)).filter((index) => index >= 0);
  const nextIncompleteStep = stepCompletion.findIndex((done) => !done);
  const activeStepIndex = loading ? 4 : nextIncompleteStep === -1 ? 4 : nextIncompleteStep;
  const elapsedSeconds = runStartedAt === null ? 0 : Math.max(0, Math.floor((progressNow - runStartedAt) / 1000));

  async function submit() {
    if (!upload || !selectedSheet) return;
    const startedAt = Date.now();
    setRunStartedAt(startedAt);
    setProgressNow(startedAt);
    setLoading(true);
    setError(null);
    try {
      const request: ForecastRunRequest = {
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
        missingValueStrategy: "drop",
        fillMissingTimeSteps: true
      };
      const response = await runForecast(request);
      setForecastResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "实验运行失败，请检查字段、模型或测试集长度。");
    } finally {
      setLoading(false);
      setRunStartedAt(null);
    }
  }

  async function submitFinalForecast() {
    if (!forecastResult || !finalModelId) return;
    const startedAt = Date.now();
    setRunStartedAt(startedAt);
    setProgressNow(startedAt);
    setLoading(true);
    setError(null);
    try {
      setFinalForecast(await runFinalForecast(forecastResult.experimentId, finalModelId, horizon));
    } catch (err) {
      setError(err instanceof Error ? err.message : "最终预测失败，请检查最终模型是否可用。");
    } finally {
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
                    {orderedColumns.map((column) => (
                      <label key={column.name} className="flex items-center gap-2 rounded-xl px-2 py-2 text-sm hover:bg-slate-50 dark:hover:bg-white/5">
                        <input
                          type="checkbox"
                          checked={targetColumns.includes(column.name)}
                          onChange={(event) => setTargetColumns((current) => (event.target.checked ? [...current, column.name] : current.filter((item) => item !== column.name)))}
                        />
                        {column.name}
                        <Badge tone={column.inferredType === "number" ? "good" : column.inferredType === "datetime" ? "info" : "neutral"}>{column.inferredType}</Badge>
                      </label>
                    ))}
                  </div>
                  {targetColumns.length > 1 ? <p className="text-xs text-amber-600 dark:text-amber-300">多目标会按目标列分别运行单变量预测。</p> : null}
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
                <div className="grid max-h-[520px] gap-3 overflow-auto pr-1 md:grid-cols-2">
                  {sortedModels.map((model) => (
                    <ModelCard
                      key={model.id}
                      model={model}
                      resource={resourceAssessments.get(model.id) ?? assessModelResource({ model, deviceInfo, upload, sheet: selectedSheet, dataMode, targetColumns, horizon, testSize })}
                      selected={selectedModels.includes(model.id)}
                      onChange={(checked) => setSelectedModels((current) => (checked ? [...current, model.id] : current.filter((item) => item !== model.id)))}
                    />
                  ))}
                </div>
                <button className={controls.primaryButton} disabled={!targetColumns.length || !selectedModels.length || !horizonRange.compatible || loading} onClick={() => void submit()}>
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
