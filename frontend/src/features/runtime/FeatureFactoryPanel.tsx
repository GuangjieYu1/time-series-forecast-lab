import { useEffect, useMemo, useState } from "react";
import { fetchExperimentFeatureFactory } from "../../shared/api/client";
import { ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, SectionCard } from "../../shared/components/Ui";
import type { RuntimeFeatureNode, RuntimeFeaturePipelineTarget } from "../../shared/types/api";
import { FeatureEngineeringFlow } from "./FeatureEngineeringFlow";


function lifecycleLabel(value: RuntimeFeatureNode["lifecycle"]) {
  return {
    generated: "已生成",
    selected: "已选择",
    dropped: "已丢弃",
    used: "已使用",
    important: "重要"
  }[value];
}

function featureTypeLabel(value: RuntimeFeatureNode["featureType"]) {
  return {
    generated: "生成特征",
    known_future_covariate: "未来已知协变量",
    static_covariate: "静态协变量",
    unknown_future_covariate: "未来未知协变量"
  }[value];
}

function strategyLabel(value: RuntimeFeatureNode["forecastStrategy"] | RuntimeFeatureNode["backtestStrategy"]) {
  return {
    generated: "已生成",
    calendar: "日历生成",
    repeat_last_known: "重复最后已知值",
    use_test_timeline: "使用测试时间线已知值",
    use_future_rows: "读取未来空目标行",
    forecast_auxiliary: "辅助模型预测",
    drop_for_leakage: "防泄漏丢弃"
  }[value];
}

function nodeTone(node: RuntimeFeatureNode) {
  if (node.lifecycle === "important") return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-400/20 dark:bg-fuchsia-400/10 dark:text-fuchsia-200";
  if (node.lifecycle === "used" || node.lifecycle === "selected") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200";
  if (node.lifecycle === "dropped") return "border-slate-200 bg-slate-50 text-slate-500 dark:border-white/10 dark:bg-[#111827] dark:text-slate-400";
  return "border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200";
}

export function FeatureFactoryPanel({ experimentId, initialTargets = [] }: { experimentId: string; initialTargets?: RuntimeFeaturePipelineTarget[] }) {
  const [targets, setTargets] = useState<RuntimeFeaturePipelineTarget[]>(initialTargets);
  const [loading, setLoading] = useState(initialTargets.length === 0);
  const [error, setError] = useState<string | null>(null);
  const [selectedTarget, setSelectedTarget] = useState(initialTargets[0]?.targetColumn ?? "");
  const [selectedNodeId, setSelectedNodeId] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchExperimentFeatureFactory(experimentId)
      .then((response) => {
        if (cancelled) return;
        setTargets(response.targets);
        setSelectedTarget((current) => current || response.targets[0]?.targetColumn || "");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Feature Factory 加载失败。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  const target = targets.find((item) => item.targetColumn === selectedTarget) ?? targets[0] ?? null;

  useEffect(() => {
    if (!target?.lineage.length) return;
    if (!selectedNodeId || !target.lineage.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(target.lineage.find((node) => node.family !== "target")?.id ?? target.lineage[0].id);
    }
  }, [selectedNodeId, target]);

  const selectedNode = target?.lineage.find((node) => node.id === selectedNodeId) ?? target?.lineage[0] ?? null;
  const groupedByMachine = useMemo(() => {
    const groups = new Map<string, RuntimeFeatureNode[]>();
    (target?.lineage ?? [])
      .filter((node) => node.family !== "target")
      .forEach((node) => {
        const key = node.machineId ?? node.family;
        groups.set(key, [...(groups.get(key) ?? []), node]);
      });
    return groups;
  }, [target]);

  if (loading) return <LoadingBlock label="正在构建 Feature Factory..." />;
  if (error) return <ErrorBanner message={error} />;
  if (!target) {
    return (
      <SectionCard title="Feature Factory" description="当前实验还没有可回放的特征工厂快照。">
        <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
          暂无 Feature Factory 数据。
        </div>
      </SectionCard>
    );
  }

  const summary = target.summary;
  return (
    <SectionCard
      title="Feature Factory"
      description="这里展示数据如何经过不同 Generator / Loader 加工成训练特征，以及协变量在 Backtest / Forecast 中到底走了哪条策略。"
      action={<Badge tone="info">{target.detectedFrequency ? `频率 ${target.detectedFrequency}` : "频率自动识别"}</Badge>}
      className="overflow-hidden"
    >
      <div className="space-y-5">
        <div className="flex flex-wrap gap-2">
          {targets.map((item) => (
            <button
              key={item.targetColumn}
              type="button"
              onClick={() => setSelectedTarget(item.targetColumn)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                item.targetColumn === target.targetColumn
                  ? "border-cyan-300 bg-cyan-50 text-cyan-700 dark:border-cyan-400/30 dark:bg-cyan-400/10 dark:text-cyan-200"
                  : "border-slate-200 bg-white text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300"
              }`}
            >
              {item.targetColumn}
            </button>
          ))}
        </div>

        {summary ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
            {[
              ["原始列", summary.rawColumnCount],
              ["生成特征", summary.generatedFeatureCount],
              ["用户协变量", summary.userCovariateCount],
              ["已选择", summary.selectedFeatureCount],
              ["已丢弃", summary.droppedFeatureCount],
              ["重要特征", summary.importantFeatureCount],
              ["支持 SHAP", summary.shapSupportedFeatureCount]
            ].map(([label, value]) => (
              <div key={label} className="rounded-3xl border border-slate-200 bg-white px-4 py-4 text-sm dark:border-white/10 dark:bg-[#151b2e]">
                <div className="text-xs uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{label}</div>
                <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">{value}</div>
              </div>
            ))}
          </div>
        ) : null}

        <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
          <FeatureEngineeringFlow targets={[target]} mode="history" />

        <div className="text-sm font-semibold text-slate-950 dark:text-white">特征机器</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">每个特征机器展示输入源、输出特征和当前状态；协变量加载器同时展示未来已知、静态和未来未知策略。</div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {target.machines.map((machine) => (
              <div key={machine.id} className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-slate-950 dark:text-white">{machine.label}</div>
                  <Badge tone={machine.enabled ? "good" : "neutral"}>{machine.enabled ? "启用" : "未启用"}</Badge>
                </div>
                <div className="mt-3 text-xs leading-6 text-slate-600 dark:text-slate-300">
                  <div><span className="font-semibold">输入：</span>{machine.inputColumns.length ? machine.inputColumns.join("、") : "-"}</div>
                  <div className="mt-2"><span className="font-semibold">输出：</span>{machine.generatedFeatures.length ? machine.generatedFeatures.join("、") : "-"}</div>
                </div>
                <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">{machine.summary}</div>
                {machine.warnings.length ? (
                  <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                    {machine.warnings.join("；")}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        {target.covariates.length ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="text-sm font-semibold text-slate-950 dark:text-white">协变量流</div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">协变量分为未来已知、静态和未来未知三类；未来未知值只有在明确配置辅助预测后才会进入模型。</div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {target.covariates.map((covariate) => (
                <div key={covariate.name} className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-slate-950 dark:text-white">{covariate.name}</div>
                    <Badge tone={covariate.type === "known_future" ? "info" : covariate.type === "unknown_future" ? "warn" : "neutral"}>
                      {covariate.type === "known_future" ? "未来已知" : covariate.type === "unknown_future" ? "未来未知" : "静态"}
                    </Badge>
                  </div>
                  <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
                    <div>回测：{strategyLabel(covariate.backtestStrategy)}</div>
                    <div>预测：{strategyLabel(covariate.forecastStrategy)}</div>
                  </div>
                  {covariate.note ? (
                    <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                      {covariate.note}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="text-sm font-semibold text-slate-950 dark:text-white">特征流图</div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">点击节点查看来源、生成器、类型、预测与回测策略以及生命周期。</div>
            <div className="mt-4 space-y-4">
              {target.machines.map((machine) => {
                const nodes = groupedByMachine.get(machine.id) ?? [];
                return (
                  <div key={machine.id}>
                    <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                      <span>{machine.label}</span>
                      <span className="h-px flex-1 bg-slate-200 dark:bg-white/10" />
                    </div>
                    <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">输入</div>
                      <div className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{machine.inputColumns.length ? machine.inputColumns.join(" / ") : "-"}</div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        {nodes.length ? (
                          nodes.map((node) => {
                            const active = node.id === selectedNode?.id;
                            return (
                              <button
                                key={node.id}
                                type="button"
                                onClick={() => setSelectedNodeId(node.id)}
                                className={`rounded-2xl border px-3 py-2 text-left text-sm transition hover:-translate-y-0.5 ${nodeTone(node)} ${active ? "ring-2 ring-cyan-300 dark:ring-cyan-400/40" : ""}`}
                              >
                                <div className="font-medium">{node.name}</div>
                                <div className="mt-1 text-[11px] uppercase tracking-[0.12em] opacity-80">{lifecycleLabel(node.lifecycle)}</div>
                              </button>
                            );
                          })
                        ) : (
                          <div className="text-sm text-slate-500 dark:text-slate-400">当前没有输出节点。</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
            {selectedNode ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-lg font-semibold text-slate-950 dark:text-white">{selectedNode.name}</div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{selectedNode.source} → {selectedNode.generator}</div>
                  </div>
                  <span className={`rounded-full border px-3 py-1 text-xs ${nodeTone(selectedNode)}`}>{lifecycleLabel(selectedNode.lifecycle)}</span>
                </div>
                <div className="mt-4 grid gap-3">
                  {[
                    ["特征类型", featureTypeLabel(selectedNode.featureType)],
                    ["公式", selectedNode.formula],
                    ["生成器", selectedNode.generator],
                    ["预测策略", strategyLabel(selectedNode.forecastStrategy)],
                    ["回测策略", strategyLabel(selectedNode.backtestStrategy)],
                    ["使用阶段", selectedNode.usedDuring.join(" / ")],
                    ["适用模型", selectedNode.modelIds.length ? selectedNode.modelIds.join(", ") : "当前未绑定到具体模型"],
                    ["丢弃原因", selectedNode.droppedReason ?? "—"],
                    ["生命周期", selectedNode.lifecycleTrail.length ? selectedNode.lifecycleTrail.join(" → ") : lifecycleLabel(selectedNode.lifecycle)]
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm dark:bg-[#0b1020]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                      <div className="mt-2 font-medium text-slate-900 dark:text-white">{value}</div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="flex min-h-[320px] items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">选择左侧任意节点后，这里会显示 特征详情。</div>
            )}
          </div>
        </div>

        {target.selection ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-950 dark:text-white">特征筛选</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  已生成 {target.selection.generatedCount} → 已选择 {target.selection.selectedCount} → 已丢弃 {target.selection.droppedCount}
                </div>
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {target.selection.items.map((item) => (
                <div key={`${item.status}-${item.name}`} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm dark:border-white/10 dark:bg-[#0b1020]">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-slate-900 dark:text-white">{item.name}</div>
                    <Badge tone={item.status === "selected" ? "good" : "neutral"}>{item.status === "selected" ? "已选择" : "已丢弃"}</Badge>
                  </div>
                  <div className="mt-2 text-xs leading-6 text-slate-500 dark:text-slate-400">{item.reason ?? "已进入训练链路。"}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {target.warnings.length ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
            {target.warnings.join("；")}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}
