import { useEffect, useMemo, useState } from "react";
import { fetchExperimentExplainability } from "../../shared/api/client";
import { ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, SectionCard, Tabs } from "../../shared/components/Ui";
import type { ExperimentExplainabilityResponse } from "../../shared/types/api";

const EXPLAINABILITY_TIMEOUT_MS = 8000;

function formatMetric(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

export function ExplainabilityPanel({
  experimentId,
  recommendedModelId = null,
  initialPayload = null
}: {
  experimentId: string;
  recommendedModelId?: string | null;
  initialPayload?: ExperimentExplainabilityResponse | null;
}) {
  const [payload, setPayload] = useState<ExperimentExplainabilityResponse | null>(initialPayload);
  const [loading, setLoading] = useState(!initialPayload);
  const [error, setError] = useState<string | null>(null);
  const [refreshWarning, setRefreshWarning] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    setPayload(initialPayload);
    setSelectedModelId((current) => selectModelId(current, initialPayload));
    setLoading(!initialPayload);
    setError(null);
    setRefreshWarning(null);
    const timeoutPromise = new Promise<ExperimentExplainabilityResponse>((_, reject) => {
      timer = window.setTimeout(() => reject(new Error("特征解释接口响应超时，已回退到本地已保存摘要。")), EXPLAINABILITY_TIMEOUT_MS);
    });
    void Promise.race([fetchExperimentExplainability(experimentId), timeoutPromise])
      .then((response) => {
        if (cancelled) return;
        setPayload(response);
        setSelectedModelId((current) => selectModelId(current, response));
        setRefreshWarning(null);
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "特征解释加载失败。";
        if (initialPayload) {
          setRefreshWarning(message);
          setError(null);
        } else {
          setError(message);
        }
      })
      .finally(() => {
        if (timer) window.clearTimeout(timer);
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [experimentId, initialPayload]);

  const models = payload?.models ?? [];
  const selected = models.find((item) => item.modelId === selectedModelId) ?? models[0] ?? null;
  const recommendedId = payload?.recommendedModelId ?? recommendedModelId;
  const summaryText = useMemo(() => {
    if (!selected) return "当前实验还没有可回放的特征解释。";
    if (!selected.supported) return selected.warning ?? "当前模型暂不支持 SHAP。";
    return selected.shapSupported
      ? "当前展示的是树模型训练后直接持久化的 Feature Importance / SHAP 结果，不会在历史页重新训练。"
      : selected.shapWarning ?? "已保存 Feature Importance，但 SHAP 当前不可用。";
  }, [selected]);

  if (loading) return <LoadingBlock label="正在加载特征解释..." />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <SectionCard
      title="特征解释"
      description="这里回放树模型持久化保存的 Feature Importance、SHAP 与推荐单点解释。"
      action={recommendedId ? <Badge tone="good">推荐模型 {recommendedId}</Badge> : undefined}
    >
      {refreshWarning ? (
        <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
          {refreshWarning}
        </div>
      ) : null}
      {!models.length ? (
        <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
          当前实验暂未持久化特征解释。
        </div>
      ) : (
        <div className="space-y-5">
          <Tabs
            value={selected?.modelId ?? ""}
            onChange={setSelectedModelId}
            items={models.map((item) => ({
              id: item.modelId,
              label: item.modelId === recommendedId ? `${item.modelName} · 推荐` : item.modelName
            }))}
          />

          {selected ? (
            <>
              <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
                <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-lg font-semibold text-slate-950 dark:text-white">{selected.modelName}</div>
                      <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{selected.targetColumn}</div>
                    </div>
                    <Badge tone={selected.supported ? "good" : "warn"}>{selected.supported ? "支持" : "仅提示"}</Badge>
                  </div>
                  <p className="mt-4 text-sm leading-6 text-slate-600 dark:text-slate-300">{summaryText}</p>
                  {selected.warning ? (
                    <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                      {selected.warning}
                    </div>
                  ) : null}
                  {selected.shapWarning ? (
                    <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                      {selected.shapWarning}
                    </div>
                  ) : null}
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <ExplainabilityTable
                    title="Feature Importance Top 20"
                    description="模型原生 importance 排名。"
                    items={selected.featureImportance}
                    valueKey="importance"
                    emptyText="当前模型还没有持久化 Feature Importance。"
                  />
                  <ExplainabilityTable
                    title="SHAP Top 20"
                    description="平均绝对 SHAP 值，方向仅作摘要。"
                    items={selected.shapTopFeatures}
                    valueKey="meanAbsShap"
                    emptyText={selected.shapSupported ? "当前没有可展示的 SHAP 条目。" : "当前模型暂不支持 SHAP 或依赖不可用。"}
                  />
                </div>
              </div>

              <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-950 dark:text-white">推荐单点解释</div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">第一版固定展示推荐模型的最大残差回测点。</div>
                  </div>
                  {selected.singlePoint?.time ? <Badge tone="info">{selected.singlePoint.time}</Badge> : null}
                </div>
                {selected.singlePoint ? (
                  <div className="mt-4 grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
                    <div className="grid gap-3">
                      {[
                        ["实际值", formatMetric(selected.singlePoint.actual)],
                        ["预测值", formatMetric(selected.singlePoint.predicted)],
                        ["残差", formatMetric(selected.singlePoint.residual)],
                        ["绝对误差", formatMetric(selected.singlePoint.absoluteError)]
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm dark:bg-[#0b1020]">
                          <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                          <div className="mt-2 font-semibold text-slate-900 dark:text-white">{value}</div>
                        </div>
                      ))}
                    </div>
                    <div className="space-y-3">
                      {selected.singlePoint.contributions.length ? (
                        selected.singlePoint.contributions.map((item) => (
                          <div key={item.feature} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm dark:border-white/10 dark:bg-[#0b1020]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="font-medium text-slate-900 dark:text-white">{item.feature}</div>
                              <Badge tone={item.direction === "positive" ? "good" : item.direction === "negative" ? "warn" : "neutral"}>
                                {item.direction === "positive" ? "推高预测" : item.direction === "negative" ? "拉低预测" : "中性"}
                              </Badge>
                            </div>
                            <div className="mt-2 text-xs leading-6 text-slate-500 dark:text-slate-400">
                              特征值：{formatMetric(item.value)} · SHAP：{formatMetric(item.shapValue)}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                          当前没有保存到单点解释贡献明细。
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    当前模型没有可回放的单点解释。
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
      )}
    </SectionCard>
  );
}

function selectModelId(current: string, payload: ExperimentExplainabilityResponse | null | undefined): string {
  if (payload?.models.some((item) => item.modelId === current)) return current;
  return payload?.recommendedModelId || payload?.models[0]?.modelId || "";
}

function ExplainabilityTable({
  title,
  description,
  items,
  valueKey,
  emptyText
}: {
  title: string;
  description: string;
  items: ExperimentExplainabilityResponse["models"][number]["featureImportance"];
  valueKey: "importance" | "meanAbsShap";
  emptyText: string;
}) {
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
      <div className="text-sm font-semibold text-slate-950 dark:text-white">{title}</div>
      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{description}</div>
      {items.length ? (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
              <tr>
                <th className="pb-2 pr-3">#</th>
                <th className="pb-2 pr-3">Feature</th>
                <th className="pb-2 pr-3">{valueKey === "importance" ? "Importance" : "Mean Abs SHAP"}</th>
                <th className="pb-2 pr-3">方向</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 20).map((item, index) => (
                <tr key={`${item.feature}:${index}`} className="border-t border-slate-200 align-top dark:border-white/10">
                  <td className="py-3 pr-3 font-medium text-slate-900 dark:text-white">{item.rank ?? index + 1}</td>
                  <td className="py-3 pr-3 text-slate-700 dark:text-slate-200">{item.feature}</td>
                  <td className="py-3 pr-3 text-slate-700 dark:text-slate-200">{formatMetric(item[valueKey])}</td>
                  <td className="py-3 pr-3 text-slate-500 dark:text-slate-400">{item.direction ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4 rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
          {emptyText}
        </div>
      )}
    </div>
  );
}
