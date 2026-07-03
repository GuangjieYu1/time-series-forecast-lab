import type { FinalForecastResponse, ForecastRunResponse, RankedModel } from "../../shared/types/api";
import {
  buildActualVsPredictedOption,
  buildFinalForecastOption,
  buildMetricBarOption,
  buildResidualTimelineOption,
  ChartMetricKey,
  defaultVisibleModelIds
} from "../visualization/Charts";
import { renderChartOptionToDataUrl } from "../visualization/EChart";

export interface ReportVisualizationInput {
  result: ForecastRunResponse;
  finalForecast?: FinalForecastResponse | null;
  visibleModelIds?: string[];
  metric?: ChartMetricKey;
}

export interface ReportVisualArtifact {
  id: string;
  title: string;
  caption: string;
  dataUrl: string;
  summary: string[];
}

function escapeHtml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttribute(value: string) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

function metricValue(model: RankedModel, metric: ChartMetricKey) {
  return model.metrics?.[metric] ?? null;
}

function formatMetric(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

function formatPointValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value < 10 ? value.toFixed(2) : value.toFixed(1);
}

function compactTime(value: string) {
  return value.replace("T", " ").slice(0, 16);
}

function average(values: number[]) {
  if (!values.length) return 0;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function successfulModels(result: ForecastRunResponse) {
  return [...result.rankedModels]
    .filter((model) => model.status === "success" && model.metrics)
    .sort((left, right) => {
      if (left.rank !== null && right.rank !== null && left.rank !== right.rank) return left.rank - right.rank;
      return (left.metrics?.mae ?? Number.POSITIVE_INFINITY) - (right.metrics?.mae ?? Number.POSITIVE_INFINITY);
    });
}

function bestModel(result: ForecastRunResponse) {
  return successfulModels(result)[0] ?? null;
}

function runnerUpModel(result: ForecastRunResponse) {
  return successfulModels(result)[1] ?? null;
}

export async function buildReportVisualArtifacts(input: ReportVisualizationInput): Promise<ReportVisualArtifact[]> {
  const shownModelIds = (input.visibleModelIds?.length ? input.visibleModelIds : defaultVisibleModelIds(input.result)).filter(
    (modelId) => Boolean(input.result.backtest.predictions[modelId])
  );
  const best = bestModel(input.result);
  const runnerUp = runnerUpModel(input.result);
  const metric = input.metric ?? "mae";
  const artifacts: ReportVisualArtifact[] = [];

  artifacts.push({
    id: "actual-vs-predicted",
    title: "图 1：回测真实值 vs 预测值",
    caption: "展示真实值与当前重点模型在 Holdout 回测窗口中的拟合情况。",
    dataUrl: await renderChartOptionToDataUrl(
      buildActualVsPredictedOption({
        result: input.result,
        visibleModelIds: shownModelIds,
        includeToolbox: false,
        includeDataZoom: false,
        animation: false
      }),
      { width: 1280, height: 720, backgroundColor: "#ffffff" }
    ),
    summary: (() => {
      const rows = best ? input.result.backtest.predictions[best.modelId] ?? [] : [];
      const maxResidualPoint = [...rows].sort((left, right) => Math.abs(right.residual) - Math.abs(left.residual))[0];
      return [
        best ? `推荐模型为 ${best.modelName}，MAE ${formatMetric(best.metrics?.mae)}，RMSE ${formatMetric(best.metrics?.rmse)}。` : "当前没有成功模型，因此这张图主要用于确认真实值走势与失败前的预测轨迹。",
        shownModelIds.length ? `当前图中展示 ${shownModelIds.length} 个重点模型：${shownModelIds.map((modelId) => input.result.rankedModels.find((model) => model.modelId === modelId)?.modelName ?? modelId).join("、")}。` : "当前没有额外可视对比模型。",
        maxResidualPoint
          ? `最大单点偏差出现在 ${compactTime(maxResidualPoint.time)}，真实值 ${formatPointValue(maxResidualPoint.actual)}，预测值 ${formatPointValue(maxResidualPoint.predicted)}，Residual=${formatPointValue(maxResidualPoint.residual)}。`
          : "本次没有可用于计算单点偏差的回测点。"
      ];
    })()
  });

  artifacts.push({
    id: "metric-bar",
    title: `图 2：${metric.toUpperCase()} 指标对比`,
    caption: "把成功模型拉到同一坐标系下比较，便于快速看出领先梯队与性能差距。",
    dataUrl: await renderChartOptionToDataUrl(
      buildMetricBarOption({
        result: input.result,
        metric,
        includeToolbox: false,
        includeDataZoom: false,
        animation: false
      }),
      { width: 1280, height: 720, backgroundColor: "#ffffff" }
    ),
    summary: [
      best ? `${metric.toUpperCase()} 维度下当前第一名是 ${best.modelName}（${formatMetric(metricValue(best, metric))}）。` : `当前没有成功模型，因此 ${metric.toUpperCase()} 柱状图不具备推荐意义。`,
      best && runnerUp
        ? `第二名为 ${runnerUp.modelName}（${formatMetric(metricValue(runnerUp, metric))}），两者差值为 ${formatMetric((metricValue(runnerUp, metric) ?? 0) - (metricValue(best, metric) ?? 0))}。`
        : "当前没有稳定的第二名可用于差值比较。",
      `成功模型 ${successfulModels(input.result).length} 个，失败模型 ${input.result.rankedModels.filter((model) => model.status === "failed").length} 个；失败模型仍会保留在实验记录中，但不参与推荐。`
    ]
  });

  artifacts.push({
    id: "residual-timeline",
    title: "图 3：Residual 时间线",
    caption: "Residual 定义为 actual - predicted；正值代表低估，负值代表高估。",
    dataUrl: await renderChartOptionToDataUrl(
      buildResidualTimelineOption({
        result: input.result,
        visibleModelIds: shownModelIds,
        includeToolbox: false,
        includeDataZoom: false,
        animation: false
      }),
      { width: 1280, height: 720, backgroundColor: "#ffffff" }
    ),
    summary: (() => {
      const rows = best ? input.result.backtest.predictions[best.modelId] ?? [] : [];
      const positiveCount = rows.filter((point) => point.residual > 0).length;
      const negativeCount = rows.filter((point) => point.residual < 0).length;
      const earlySlice = rows.slice(0, Math.max(1, Math.ceil(rows.length / 3)));
      const lateSlice = rows.slice(-Math.max(1, Math.ceil(rows.length / 3)));
      const earlyMean = average(earlySlice.map((point) => point.residual));
      const lateMean = average(lateSlice.map((point) => point.residual));
      return [
        best ? `${best.modelName} 在回测窗口中共有 ${positiveCount} 个正残差、${negativeCount} 个负残差，可用于判断低估/高估是否偏向一侧。` : "当前没有可用的推荐模型残差序列。",
        rows.length ? `残差均值从前段的 ${formatPointValue(earlyMean)} 变化到后段的 ${formatPointValue(lateMean)}，可以帮助判断误差是否在尾部漂移。` : "当前没有足够的回测点来判断误差漂移。",
        rows.length ? `平均绝对误差约为 ${formatPointValue(average(rows.map((point) => point.absoluteError)))}。` : "当前没有足够的回测点来计算平均绝对误差。"
      ];
    })()
  });

  if (input.finalForecast?.forecast.length) {
    const first = input.finalForecast.forecast[0];
    const last = input.finalForecast.forecast[input.finalForecast.forecast.length - 1];
    const intervalWidths = input.finalForecast.forecast
      .map((point) => (point.upper !== null && point.lower !== null ? point.upper - point.lower : null))
      .filter((value): value is number => value !== null);

    artifacts.push({
      id: "final-forecast",
      title: "图 4：最终预测曲线",
      caption: "使用完整历史重新训练后的最终模型，对未来 horizon 窗口给出点预测与区间预测。",
      dataUrl: await renderChartOptionToDataUrl(
        buildFinalForecastOption(input.finalForecast, {
          includeToolbox: false,
          includeDataZoom: false,
          animation: false
        }),
        { width: 1280, height: 720, backgroundColor: "#ffffff" }
      ),
      summary: [
        `最终预测模型为 ${input.finalForecast.modelInfo.name}，预测窗口共 ${input.finalForecast.forecast.length} 个时间点。`,
        `预测值从 ${formatPointValue(first.predicted)} 变化到 ${formatPointValue(last.predicted)}，净变化 ${formatPointValue(last.predicted - first.predicted)}。`,
        intervalWidths.length ? `平均预测区间宽度约为 ${formatPointValue(average(intervalWidths))}，可作为未来不确定性量级的参考。` : "当前模型未提供完整区间预测，因此只能解读点预测趋势。"
      ]
    });
  }

  return artifacts;
}

export function buildVisualAppendixMarkdown(artifacts: ReportVisualArtifact[]) {
  if (!artifacts.length) return "";
  const lines = ["## 附录：图像与结果解读", ""];
  artifacts.forEach((artifact) => {
    lines.push(`### ${artifact.title}`, "");
    lines.push(`> ${artifact.caption}`, "");
    artifact.summary.forEach((line) => lines.push(`- ${line}`));
    lines.push("");
  });
  return lines.join("\n").trim();
}

export function renderVisualAppendixHtml(artifacts: ReportVisualArtifact[]) {
  if (!artifacts.length) return "";
  return `
    <section class="report-visuals">
      <h2>附录：图像与结果解读</h2>
      ${artifacts
        .map(
          (artifact) => `
            <article class="report-figure">
              <h3>${escapeHtml(artifact.title)}</h3>
              <p class="report-figure-caption">${escapeHtml(artifact.caption)}</p>
              <figure>
                <img src="${escapeAttribute(artifact.dataUrl)}" alt="${escapeAttribute(artifact.title)}" />
              </figure>
              <ul>
                ${artifact.summary.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
              </ul>
            </article>
          `
        )
        .join("")}
    </section>
  `;
}
