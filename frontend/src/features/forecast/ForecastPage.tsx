import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Link } from "react-router-dom";
import { fetchDevice, fetchModels, runFinalForecast, runForecast } from "../../shared/api/client";
import { DataTable } from "../../shared/components/Table";
import { EmptyState, ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, Stepper, surface, Tabs } from "../../shared/components/Ui";
import { zhCN } from "../../shared/i18n/zhCN";
import type { ForecastRunRequest, ForecastRunResponse, ModelCapability, RankedModel } from "../../shared/types/api";
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

const modelDefaults = ["naive", "seasonal_naive", "moving_average", "arima", "ets", "prophet", "timesfm", "xgboost", "lightgbm", "random_forest"];
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

function RunningProgress({ finalForecastMode = false }: { finalForecastMode?: boolean }) {
  const items = finalForecastMode
    ? ["读取完整历史数据", "重新训练最终模型", "生成未来预测", "更新预测图表"]
    : ["校验字段配置", "构建时间序列", "运行模型回测", "计算残差指标"];
  return (
    <SectionCard
      title={finalForecastMode ? "正在运行最终预测" : "正在运行预测实验"}
      description={finalForecastMode ? "系统正在用最终模型预测未来时间点。" : "系统正在执行 holdout 回测，部分模型可能需要更长时间。"}
      className="overflow-hidden"
    >
      <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
        <div className="h-full w-2/5 animate-[progress_1.4s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400" />
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-4">
        {items.map((item) => (
          <div key={item} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300">
            {item}
          </div>
        ))}
      </div>
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

function ModelCard({ model, selected, onChange }: { model: ModelCapability; selected: boolean; onChange: (checked: boolean) => void }) {
  const runnable = isRunnableModel(model);
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
          <div className="font-semibold text-slate-950 dark:text-white">{model.name}</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{model.modelFamily || model.category}</div>
        </div>
        <Badge tone={modelStatusTone(model)}>{modelStatusText(model)}</Badge>
      </div>
      <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{zhCN.modelDescriptions[model.id as keyof typeof zhCN.modelDescriptions] ?? model.shortDescription}</p>
      {!runnable && model.unavailableReason ? <p className="mt-2 text-xs text-amber-600 dark:text-amber-300">{model.unavailableReason}</p> : null}
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetchModels()
      .then((modelList) => {
        setModels(modelList);
        const runnableDefaults = modelList.filter((model) => modelDefaults.includes(model.id) && isRunnableModel(model)).map((model) => model.id);
        setSelectedModels(runnableDefaults);
      })
      .catch(() => setModels([]));
    void fetchDevice().then(setDevice).catch(() => setDevice("cpu"));
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

  const orderedColumns = useMemo(() => {
    if (!selectedSheet) return [];
    return [...selectedSheet.columns].sort((left, right) => {
      const score = (type: string) => (type === "datetime" ? 0 : type === "number" ? 1 : 2);
      return score(left.inferredType) - score(right.inferredType);
    });
  }, [selectedSheet]);

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

  async function submit() {
    if (!upload || !selectedSheet) return;
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
    }
  }

  async function submitFinalForecast() {
    if (!forecastResult || !finalModelId) return;
    setLoading(true);
    setError(null);
    try {
      setFinalForecast(await runFinalForecast(forecastResult.experimentId, finalModelId, horizon));
    } catch (err) {
      setError(err instanceof Error ? err.message : "最终预测失败，请检查最终模型是否可用。");
    } finally {
      setLoading(false);
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
      {loading ? <RunningProgress finalForecastMode={Boolean(forecastResult)} /> : null}

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

            <SectionCard title="Step 3-5：模型与回测" description="只允许选择当前可运行模型；未安装或计划中模型可在模型库查看原因。">
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
                <div className="grid max-h-[520px] gap-3 overflow-auto pr-1 md:grid-cols-2">
                  {models.map((model) => (
                    <ModelCard
                      key={model.id}
                      model={model}
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
