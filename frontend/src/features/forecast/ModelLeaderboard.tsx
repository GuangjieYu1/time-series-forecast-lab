import { DataTable } from "../../shared/components/Table";
import { Badge } from "../../shared/components/Ui";
import type { RankedModel } from "../../shared/types/api";

function metricText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

function numericExtremes(values: Array<number | null | undefined>) {
  const finite = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (finite.length < 2) return null;
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  return min === max ? null : { min, max };
}

export function ModelLeaderboard({ rows, recommendedModelId }: { rows: RankedModel[]; recommendedModelId: string | null }) {
  const comparableRows = rows.filter((row) => row.status === "success");
  const extremes = {
    mae: numericExtremes(comparableRows.map((row) => row.metrics?.mae)), mse: numericExtremes(comparableRows.map((row) => row.metrics?.mse)),
    rmse: numericExtremes(comparableRows.map((row) => row.metrics?.rmse)), wape: numericExtremes(comparableRows.map((row) => row.metrics?.wape)),
    fit: numericExtremes(comparableRows.map((row) => row.runtime.fitSeconds)), predict: numericExtremes(comparableRows.map((row) => row.runtime.predictSeconds))
  };
  const highlightedValue = (row: RankedModel, value: number | null | undefined, key: keyof typeof extremes, text: string) => {
    const range = extremes[key];
    const tone = row.status === "success" && range && value === range.min ? "best" : row.status === "success" && range && value === range.max ? "worst" : null;
    return <span className={`-mx-3 -my-2 block whitespace-nowrap px-3 py-2 font-medium ${tone === "best" ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200" : tone === "worst" ? "bg-red-50 text-red-700 dark:bg-red-400/10 dark:text-red-200" : ""}`}>{text}</span>;
  };
  return <DataTable<RankedModel> data={rows} columns={[
    { header: "排名", cell: ({ row }) => row.original.rank ?? "-" },
    { header: "模型", cell: ({ row }) => <span className="whitespace-nowrap">{row.original.modelName}</span> },
    { header: "MAE", cell: ({ row }) => highlightedValue(row.original, row.original.metrics?.mae, "mae", metricText(row.original.metrics?.mae)) },
    { header: "MSE", cell: ({ row }) => highlightedValue(row.original, row.original.metrics?.mse, "mse", metricText(row.original.metrics?.mse)) },
    { header: "RMSE", cell: ({ row }) => highlightedValue(row.original, row.original.metrics?.rmse, "rmse", metricText(row.original.metrics?.rmse)) },
    { header: "WAPE", cell: ({ row }) => highlightedValue(row.original, row.original.metrics?.wape, "wape", metricText(row.original.metrics?.wape)) },
    { header: "训练耗时", cell: ({ row }) => highlightedValue(row.original, row.original.runtime.fitSeconds, "fit", `${row.original.runtime.fitSeconds}s`) },
    { header: "预测耗时", cell: ({ row }) => highlightedValue(row.original, row.original.runtime.predictSeconds, "predict", `${row.original.runtime.predictSeconds}s`) },
    { header: "推荐", cell: ({ row }) => row.original.modelId === recommendedModelId ? <Badge tone="good">推荐模型</Badge> : null },
    { header: "状态", cell: ({ row }) => row.original.status === "success" ? <Badge tone="good">成功</Badge> : <Badge tone="bad">{row.original.error ?? "失败"}</Badge> }
  ]} />;
}