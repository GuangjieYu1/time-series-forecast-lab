import type { EChartsOption } from "echarts";
import { EChart } from "./EChart";
import type { FinalForecastResponse, ForecastRunResponse, RankedModel } from "../../shared/types/api";
import { zhCN } from "../../shared/i18n/zhCN";

export const modelColorMap: Record<string, string> = {
  actual: "#00E5FF",
  timesfm: "#8B5CF6",
  prophet: "#2563EB",
  arima: "#F97316",
  ets: "#10B981",
  xgboost: "#EF4444",
  lightgbm: "#06B6D4",
  random_forest: "#EC4899",
  naive: "#64748B",
  seasonal_naive: "#94A3B8",
  moving_average: "#EAB308"
};

const palette = Object.values(modelColorMap);

export function defaultVisibleModelIds(result: ForecastRunResponse) {
  const top = result.rankedModels.filter((model) => model.status === "success" && model.rank !== null && model.rank <= 3).map((model) => model.modelId);
  if (result.rankedModels.some((model) => model.modelId === "timesfm" && model.status === "success")) top.push("timesfm");
  return Array.from(new Set(top));
}

function modelName(models: RankedModel[], modelId: string) {
  return models.find((model) => model.modelId === modelId)?.modelName ?? modelId;
}

function baseOption(title: string): EChartsOption {
  return {
    title: { text: title, left: 10, top: 8, textStyle: { fontSize: 14, fontWeight: 600, color: "#94A3B8" } },
    animation: true,
    tooltip: { trigger: "axis", borderWidth: 1, confine: true, backgroundColor: "rgba(15,23,42,0.92)", borderColor: "rgba(148,163,184,0.25)", textStyle: { color: "#F8FAFC" } },
    legend: { top: 36, type: "scroll", textStyle: { color: "#94A3B8" } },
    toolbox: { right: 8, feature: { saveAsImage: {} } },
    grid: { left: 48, right: 24, top: 82, bottom: 56 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 16 }],
    color: palette
  };
}

function compactTimeLabel(value: string | number) {
  const text = String(value);
  const normalized = text.replace("T", " ");
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ ](\d{2}):(\d{2}))?/);
  if (!match) return text;
  const [, , month, day, hour, minute] = match;
  if (hour && minute && `${hour}:${minute}` !== "00:00") return `${month}-${day} ${hour}:${minute}`;
  return `${month}-${day}`;
}

function timeCategoryAxis(times: string[]) {
  return {
    type: "category" as const,
    data: times,
    boundaryGap: false,
    axisLabel: { color: "#94A3B8", formatter: compactTimeLabel },
    axisTick: { alignWithLabel: true }
  };
}

function valueAxis({ scale = false, zeroLine = false }: { scale?: boolean; zeroLine?: boolean } = {}) {
  return {
    type: "value" as const,
    scale,
    axisLabel: { color: "#94A3B8" },
    splitLine: { lineStyle: { color: "rgba(148,163,184,0.14)" } },
    axisLine: zeroLine ? { show: true, lineStyle: { color: "rgba(148,163,184,0.28)" } } : undefined
  };
}

function lineStyle(modelId: string, width = 2) {
  return {
    width: modelId === "timesfm" ? 3 : width,
    type: ["naive", "seasonal_naive", "moving_average"].includes(modelId) ? "dashed" : "solid",
    color: modelColorMap[modelId],
    opacity: 0.68
  };
}

function actualLineStyle(width = 5) {
  return {
    width,
    color: modelColorMap.actual,
    opacity: 1,
    shadowBlur: 12,
    shadowColor: "rgba(34,211,238,0.85)"
  };
}

export function ActualVsPredictedChart({ result, visibleModelIds, height }: { result: ForecastRunResponse; visibleModelIds?: string[]; height?: number }) {
  const shown = visibleModelIds ?? defaultVisibleModelIds(result);
  const times = result.backtest.actual.map((point) => point.time);
  const series = [
    {
      name: zhCN.charts.actual,
      type: "line",
      smooth: true,
      data: result.backtest.actual.map((point) => point.value),
      lineStyle: actualLineStyle(),
      z: 20,
      showSymbol: false,
      emphasis: { focus: "series", lineStyle: actualLineStyle(6) }
    },
    ...shown
      .filter((id) => result.backtest.predictions[id])
      .map((id) => ({
        name: modelName(result.rankedModels, id),
        type: "line",
        smooth: true,
        data: result.backtest.predictions[id].map((point) => point.predicted),
        lineStyle: lineStyle(id)
      }))
  ];
  return <EChart height={height} option={{ ...baseOption(zhCN.charts.actualVsPredicted), xAxis: timeCategoryAxis(times), yAxis: valueAxis({ scale: true }), series: series as EChartsOption["series"] }} />;
}

export function ResidualTimelineChart({ result, visibleModelIds }: { result: ForecastRunResponse; visibleModelIds?: string[] }) {
  const shown = visibleModelIds ?? defaultVisibleModelIds(result);
  const times = result.backtest.actual.map((point) => point.time);
  const series = shown
    .filter((id) => result.backtest.predictions[id])
    .map((id) => ({
      name: modelName(result.rankedModels, id),
      type: "line",
      smooth: true,
      data: result.backtest.predictions[id].map((point) => point.residual),
      lineStyle: lineStyle(id),
      markLine: { silent: true, data: [{ yAxis: 0 }] }
    }));
  return <EChart option={{ ...baseOption(zhCN.charts.residualTimeline), xAxis: timeCategoryAxis(times), yAxis: valueAxis({ zeroLine: true }), series: series as EChartsOption["series"] }} />;
}

export function MetricBarChart({ result, metric }: { result: ForecastRunResponse; metric: keyof NonNullable<RankedModel["metrics"]> }) {
  const successful = result.rankedModels.filter((model) => model.status === "success" && model.metrics);
  return (
    <EChart
      option={{
        ...baseOption(`${metric.toUpperCase()} ${zhCN.charts.metricBar}`),
        xAxis: { type: "category", data: successful.map((model) => model.modelName), axisLabel: { color: "#94A3B8" } },
        yAxis: valueAxis(),
        series: [{ type: "bar", data: successful.map((model) => ({ value: model.metrics?.[metric] ?? 0, itemStyle: { color: modelColorMap[model.modelId] ?? "#4F46E5" } })), barMaxWidth: 44 }]
      }}
    />
  );
}

export function ResidualDistributionChart({ result, visibleModelIds }: { result: ForecastRunResponse; visibleModelIds?: string[] }) {
  const shown = visibleModelIds ?? defaultVisibleModelIds(result);
  const series = shown
    .filter((id) => result.backtest.predictions[id])
    .map((id) => ({
      name: modelName(result.rankedModels, id),
      type: "bar",
      data: result.backtest.predictions[id].map((point) => [Math.round(point.residual * 100) / 100, 1])
    }));
  return <EChart option={{ ...baseOption(zhCN.charts.residualDistribution), xAxis: valueAxis({ scale: true }), yAxis: valueAxis(), series: series as EChartsOption["series"] }} />;
}

export function PredictedResidualScatterChart({ result, visibleModelIds }: { result: ForecastRunResponse; visibleModelIds?: string[] }) {
  const shown = visibleModelIds ?? defaultVisibleModelIds(result);
  const series = shown
    .filter((id) => result.backtest.predictions[id])
    .map((id) => ({
      name: modelName(result.rankedModels, id),
      type: "scatter",
      itemStyle: { color: modelColorMap[id] },
      data: result.backtest.predictions[id].map((point) => [point.predicted, point.residual])
    }));
  return <EChart option={{ ...baseOption(zhCN.charts.predictedResidualScatter), xAxis: valueAxis({ scale: true }), yAxis: valueAxis({ zeroLine: true }), series: series as EChartsOption["series"] }} />;
}

export function AbsoluteErrorTimelineChart({ result, visibleModelIds }: { result: ForecastRunResponse; visibleModelIds?: string[] }) {
  const shown = visibleModelIds ?? defaultVisibleModelIds(result);
  const times = result.backtest.actual.map((point) => point.time);
  const series = shown
    .filter((id) => result.backtest.predictions[id])
    .map((id) => ({
      name: modelName(result.rankedModels, id),
      type: "line",
      smooth: true,
      lineStyle: lineStyle(id),
      data: result.backtest.predictions[id].map((point) => point.absoluteError)
    }));
  return <EChart option={{ ...baseOption(zhCN.charts.absoluteErrorTimeline), xAxis: timeCategoryAxis(times), yAxis: valueAxis(), series: series as EChartsOption["series"] }} />;
}

export function NormalizedMetricChart({ result }: { result: ForecastRunResponse }) {
  const successful = result.rankedModels.filter((model) => model.status === "success" && model.metrics);
  const metrics = ["mae", "rmse", "wape"] as const;
  const maxByMetric = Object.fromEntries(metrics.map((metric) => [metric, Math.max(...successful.map((model) => model.metrics?.[metric] ?? 0), 1)]));
  const series = metrics.map((metric) => ({
    name: metric.toUpperCase(),
    type: "bar",
    data: successful.map((model) => {
      const value = model.metrics?.[metric] ?? 0;
      return Number((value / maxByMetric[metric]).toFixed(4));
    })
  }));
  return <EChart option={{ ...baseOption(zhCN.charts.normalizedMetric), xAxis: { type: "category", data: successful.map((model) => model.modelName), axisLabel: { color: "#94A3B8" } }, yAxis: { ...valueAxis(), max: 1 }, series: series as EChartsOption["series"] }} />;
}

export function FinalForecastChart({ finalForecast }: { finalForecast: FinalForecastResponse | null }) {
  if (!finalForecast) {
    return (
      <div className="flex h-[360px] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
        选择最终模型后，这里会显示未来预测曲线和置信区间。
      </div>
    );
  }
  const historyTimes = finalForecast.history.map((point) => point.time);
  const futureTimes = finalForecast.forecast.map((point) => point.time);
  const times = [...historyTimes, ...futureTimes];
  const historyValues = [...finalForecast.history.map((point) => point.value), ...Array(futureTimes.length).fill(null)];
  const forecastValues = [...Array(historyTimes.length).fill(null), ...finalForecast.forecast.map((point) => point.predicted)];
  const lower = [...Array(historyTimes.length).fill(null), ...finalForecast.forecast.map((point) => point.lower)];
  const upper = [...Array(historyTimes.length).fill(null), ...finalForecast.forecast.map((point) => point.upper)];
  return (
    <EChart
      option={{
        ...baseOption(zhCN.charts.finalForecast),
        xAxis: timeCategoryAxis(times),
        yAxis: valueAxis({ scale: true }),
        series: [
          { name: zhCN.charts.history, type: "line", smooth: true, data: historyValues, lineStyle: actualLineStyle(4), z: 20, showSymbol: false },
          { name: finalForecast.modelInfo.name, type: "line", smooth: true, data: forecastValues, lineStyle: { width: 3, color: modelColorMap[finalForecast.finalModelId] ?? "#818CF8" } },
          { name: zhCN.charts.lower, type: "line", smooth: true, data: lower, lineStyle: { type: "dashed" } },
          { name: zhCN.charts.upper, type: "line", smooth: true, data: upper, lineStyle: { type: "dashed" } }
        ],
        markLine: { data: [{ xAxis: historyTimes[historyTimes.length - 1] }] }
      }}
    />
  );
}
