import { useEffect, useMemo, useState } from "react";
import { fetchExperimentFeatureFactory } from "../../shared/api/client";
import { ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, SectionCard } from "../../shared/components/Ui";
import type {
  RuntimeCovariateDescriptor,
  RuntimeFeatureMachine,
  RuntimeFeatureNode,
  RuntimeFeaturePipelineTarget
} from "../../shared/types/api";
import { FeatureEngineeringFlow } from "./FeatureEngineeringFlow";

const machineOrder = ["lag_generator", "rolling_generator", "calendar_generator", "holiday_generator", "covariate_loader"];

function lifecycleLabel(value: RuntimeFeatureNode["lifecycle"]) {
  return {
    generated: "Generated",
    selected: "Selected",
    dropped: "Dropped",
    used: "Used",
    important: "Important"
  }[value];
}

function featureTypeLabel(value: RuntimeFeatureNode["featureType"]) {
  return {
    generated: "生成特征",
    known_future_covariate: "未来已知协变量",
    static_covariate: "静态协变量"
  }[value];
}

function statusTone(status: RuntimeFeaturePipelineTarget["status"] | RuntimeFeatureMachine["status"]) {
  if (status === "completed") return "good";
  if (status === "running") return "info";
  if (status === "failed") return "bad";
  return "neutral";
}

function strategyLabel(value: RuntimeFeatureNode["forecastStrategy"] | RuntimeFeatureNode["backtestStrategy"] | RuntimeCovariateDescriptor["forecastStrategy"] | RuntimeCovariateDescriptor["backtestStrategy"]) {
  return {
    generated: "Generated",
    calendar: "Calendar",
    repeat_last_known: "Repeat Last Known",
    use_test_timeline: "Use Test Timeline",
    use_future_rows: "Use Future Rows",
    historical_mean: "Historical Mean",
    use_test_values: "Use Test Values"
  }[value];
}

function nodeTone(node: RuntimeFeatureNode) {
  if (node.lifecycle === "important") return "border-fuchsia-300 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-400/30 dark:bg-fuchsia-400/10 dark:text-fuchsia-200";
  if (node.lifecycle === "used" || node.lifecycle === "selected") return "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-200";
  if (node.lifecycle === "dropped") return "border-slate-200 bg-slate-50 text-slate-500 dark:border-white/10 dark:bg-[#111827] dark:text-slate-400";
  return "border-cyan-300 bg-cyan-50 text-cyan-700 dark:border-cyan-400/30 dark:bg-cyan-400/10 dark:text-cyan-200";
}

function formatMetric(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "-";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const rest = totalSeconds % 60;
  return `${minutes}m ${rest}s`;
}

function featureMeaning(node: RuntimeFeatureNode) {
  if (node.featureType === "known_future_covariate") return "这是未来天然已知的协变量，会沿测试时间线或日历特征进入模型。";
  if (node.featureType === "static_covariate") return "这是静态协变量，训练期使用真实历史值，预测期固定采用 repeat last known。";
  if (/lag/i.test(node.name) || /lag/i.test(node.formula)) return "这是历史滞后值，用过去的观测点帮助模型判断趋势与季节性。";
  if (/rolling/i.test(node.name) || /rolling/i.test(node.formula)) return "这是滚动统计特征，用局部窗口的均值/波动来平滑短期噪声。";
  if (/holiday/i.test(node.name) || /holiday/i.test(node.source)) return "这是节假日相关特征，用来提示节日窗口或调休日历。";
  if (/month|weekday|quarter|week/i.test(node.name)) return "这是日历类特征，用日期本身衍生出周期位置。";
  return "这是特征工厂输出的训练特征，用于帮助模型学习时间模式。";
}

function buildGraphNodes(target: RuntimeFeaturePipelineTarget) {
  const sourceNames = Array.from(new Set(target.lineage.map((node) => node.source)));
  const featureNodes = [...target.lineage]
    .filter((node) => node.family !== "target")
    .sort((left, right) => {
      const rank = { important: 0, selected: 1, used: 2, generated: 3, dropped: 4 } as const;
      return rank[left.lifecycle] - rank[right.lifecycle] || left.name.localeCompare(right.name, "zh-CN");
    })
    .slice(0, 14);
  const machineNames = target.machines.map((machine) => ({ id: machine.id, label: machine.label }));
  const machineById = new Map(machineNames.map((machine) => [machine.id, machine.label] as const));

  const layout = {
    sourceX: 36,
    machineX: 230,
    featureX: 450,
    selectionX: 700,
    modelX: 900,
    explanationX: 1060,
    top: 50,
    gapY: 68
  };
  const sourceY = new Map(sourceNames.map((name, index) => [name, layout.top + index * layout.gapY]));
  const machineY = new Map(machineNames.map((machine, index) => [machine.id, layout.top + index * layout.gapY]));
  const featureY = new Map(featureNodes.map((node, index) => [node.id, layout.top + index * 54]));

  const edges = featureNodes.flatMap((node) => [
    { from: { x: layout.sourceX + 132, y: (sourceY.get(node.source) ?? layout.top) + 18 }, to: { x: layout.machineX, y: (machineY.get(node.machineId ?? "") ?? layout.top) + 18 }, key: `${node.id}:source` },
    { from: { x: layout.machineX + 132, y: (machineY.get(node.machineId ?? "") ?? layout.top) + 18 }, to: { x: layout.featureX, y: (featureY.get(node.id) ?? layout.top) + 18 }, key: `${node.id}:machine` },
    { from: { x: layout.featureX + 182, y: (featureY.get(node.id) ?? layout.top) + 18 }, to: { x: layout.selectionX, y: layout.top + 18 }, key: `${node.id}:selection` },
    { from: { x: layout.selectionX + 132, y: layout.top + 18 }, to: { x: layout.modelX, y: layout.top + 18 }, key: `${node.id}:model` },
    { from: { x: layout.modelX + 132, y: layout.top + 18 }, to: { x: layout.explanationX, y: layout.top + 18 }, key: `${node.id}:explanation` }
  ]);

  return { sourceNames, machineNames, machineById, featureNodes, sourceY, machineY, featureY, edges, layout };
}

export function FeatureFactoryPanel({ experimentId, initialTargets = [] }: { experimentId: string; initialTargets?: RuntimeFeaturePipelineTarget[] }) {
  const [targets, setTargets] = useState<RuntimeFeaturePipelineTarget[]>(initialTargets);
  const [loading, setLoading] = useState(initialTargets.length === 0);
  const [error, setError] = useState<string | null>(null);
  const [selectedTarget, setSelectedTarget] = useState(initialTargets[0]?.targetColumn ?? "");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [hoveredNodeId, setHoveredNodeId] = useState("");

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
  const graph = useMemo(() => (target ? buildGraphNodes(target) : null), [target]);
  const machines = useMemo(
    () =>
      machineOrder
        .map((id) => target?.machines.find((machine) => machine.id === id))
        .filter((machine): machine is RuntimeFeatureMachine => Boolean(machine)),
    [target]
  );

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
      description="这里把特征工程收成三段：Pipeline Timeline、Feature Machines、Simplified Feature Flow Graph。协变量也作为 Covariate Loader 的一部分进入同一条数据流。"
      action={<Badge tone="info">{target.detectedFrequency ? `频率 ${target.detectedFrequency}` : "频率自动识别"}</Badge>}
      className="overflow-hidden"
    >
      <div className="space-y-6">
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
              ["Raw Columns", summary.rawColumnCount],
              ["Generated Features", summary.generatedFeatureCount],
              ["User Covariates", summary.userCovariateCount],
              ["Selected", summary.selectedFeatureCount],
              ["Dropped", summary.droppedFeatureCount],
              ["Important", summary.importantFeatureCount],
              ["SHAP Supported", summary.shapSupportedFeatureCount]
            ].map(([label, value]) => (
              <div key={label} className="rounded-3xl border border-slate-200 bg-white px-4 py-4 text-sm dark:border-white/10 dark:bg-[#151b2e]">
                <div className="text-xs uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{label}</div>
                <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">{value}</div>
              </div>
            ))}
          </div>
        ) : null}

        <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="text-sm font-semibold text-slate-950 dark:text-white">Pipeline Timeline</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">基于现有 FeatureEngineeringFlow 展示 Raw Data → Cleaning → Feature Factory → Feature Selection → Training → Feature Importance → SHAP。</div>
          <div className="mt-4">
            <FeatureEngineeringFlow targets={[target]} mode="history" />
          </div>
          <div className="mt-4 grid gap-3 xl:grid-cols-4">
            {target.steps.map((step) => (
              <div key={step.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-white/10 dark:bg-[#0b1020]">
                <div className="flex items-start justify-between gap-3">
                  <div className="font-semibold text-slate-900 dark:text-white">{step.label}</div>
                  <Badge tone={statusTone(step.status)}>{step.status === "completed" ? "已完成" : step.status === "running" ? "进行中" : step.status === "failed" ? "失败" : "待开始"}</Badge>
                </div>
                <div className="mt-3 text-xs leading-6 text-slate-500 dark:text-slate-400">
                  <div>输入：{step.inputSummary || "-"}</div>
                  <div>输出：{step.outputSummary || "-"}</div>
                  <div>耗时：{formatDuration(step.elapsedSeconds)}</div>
                </div>
                {step.warnings.length ? (
                  <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                    {step.warnings.join("；")}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="text-sm font-semibold text-slate-950 dark:text-white">Feature Machines</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">固定展示 Lag / Rolling / Calendar / Holiday / Covariate Loader 五台机器，并把协变量策略直接放进 Covariate Loader。</div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {machines.map((machine) => (
              <div key={machine.id} className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-slate-950 dark:text-white">{machine.label}</div>
                  <Badge tone={statusTone(machine.status)}>{machine.status === "completed" ? "已完成" : machine.status === "running" ? "进行中" : machine.status === "failed" ? "失败" : "待开始"}</Badge>
                </div>
                <div className="mt-3 text-xs leading-6 text-slate-600 dark:text-slate-300">
                  <div>输入：{machine.inputColumns.length ? machine.inputColumns.join("、") : "-"}</div>
                  <div>输出：{machine.generatedFeatures.length ? machine.generatedFeatures.slice(0, 5).join("、") : "-"}</div>
                  <div>耗时：{formatDuration(machine.durationSeconds)}</div>
                </div>
                <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">{machine.summary}</div>
                {machine.id === "covariate_loader" && target.covariates.length ? (
                  <div className="mt-3 space-y-2">
                    {target.covariates.map((covariate) => (
                      <div key={covariate.name} className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-white/10 dark:bg-[#151b2e]">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-900 dark:text-white">{covariate.name}</span>
                          <Badge tone={covariate.type === "known_future" ? "info" : covariate.leakageRisk ? "warn" : "neutral"}>
                            {covariate.type === "known_future" ? "Known Future" : "Static"}
                          </Badge>
                        </div>
                        <div className="mt-2 leading-6 text-slate-500 dark:text-slate-400">
                          Backtest：{strategyLabel(covariate.backtestStrategy)}
                          <br />
                          Forecast：{strategyLabel(covariate.forecastStrategy)}
                        </div>
                        {covariate.note ? <div className="mt-2 text-amber-700 dark:text-amber-200">{covariate.note}</div> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {machine.warnings.length ? (
                  <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                    {machine.warnings.join("；")}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-950 dark:text-white">Simplified Feature Flow Graph</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">第一版使用轻量 SVG 只读图。hover 会高亮上下游，click 会把右侧详情切到该 feature。</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge tone="info">selected 高亮</Badge>
                <Badge tone="neutral">dropped 灰化</Badge>
                <Badge tone="good">importance / shap badge</Badge>
              </div>
            </div>
            {graph ? (
              <div className="mt-4 overflow-x-auto rounded-3xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">
                <svg viewBox="0 0 1200 920" className="min-w-[1080px]">
                  {graph.edges.map((edge) => {
                    const active = hoveredNodeId ? edge.key.startsWith(`${hoveredNodeId}:`) : selectedNodeId ? edge.key.startsWith(`${selectedNodeId}:`) : false;
                    return (
                      <path
                        key={edge.key}
                        d={`M ${edge.from.x} ${edge.from.y} C ${edge.from.x + 40} ${edge.from.y}, ${edge.to.x - 40} ${edge.to.y}, ${edge.to.x} ${edge.to.y}`}
                        fill="none"
                        stroke={active ? "#22d3ee" : "#475569"}
                        strokeOpacity={active ? 0.95 : 0.38}
                        strokeWidth={active ? 2.5 : 1.4}
                      />
                    );
                  })}

                  {graph.sourceNames.map((name) => (
                    <g key={name}>
                      <rect x={graph.layout.sourceX} y={graph.sourceY.get(name)} rx="16" width="132" height="36" fill="#0f172a" stroke="#334155" />
                      <text x={graph.layout.sourceX + 12} y={(graph.sourceY.get(name) ?? 0) + 22} fill="#e2e8f0" fontSize="12">{name}</text>
                    </g>
                  ))}

                  {graph.machineNames.map((machine) => (
                    <g key={machine.id}>
                      <rect x={graph.layout.machineX} y={graph.machineY.get(machine.id)} rx="16" width="132" height="36" fill="#132338" stroke="#21516d" />
                      <text x={graph.layout.machineX + 12} y={(graph.machineY.get(machine.id) ?? 0) + 22} fill="#bae6fd" fontSize="12">{machine.label}</text>
                    </g>
                  ))}

                  {graph.featureNodes.map((node) => {
                    const y = graph.featureY.get(node.id) ?? 0;
                    const active = hoveredNodeId === node.id || selectedNodeId === node.id;
                    const important = node.importance !== null || node.shap !== null;
                    return (
                      <g
                        key={node.id}
                        onMouseEnter={() => setHoveredNodeId(node.id)}
                        onMouseLeave={() => setHoveredNodeId("")}
                        onClick={() => setSelectedNodeId(node.id)}
                        style={{ cursor: "pointer" }}
                      >
                        <rect
                          x={graph.layout.featureX}
                          y={y}
                          rx="16"
                          width="182"
                          height="36"
                          fill={node.lifecycle === "dropped" ? "#0f172a" : active ? "#083344" : "#172554"}
                          stroke={node.lifecycle === "dropped" ? "#475569" : active ? "#22d3ee" : "#6366f1"}
                          strokeWidth={active ? 2.5 : 1.5}
                          opacity={node.lifecycle === "dropped" ? 0.7 : 1}
                        />
                        <text x={graph.layout.featureX + 12} y={y + 22} fill="#e2e8f0" fontSize="12">{node.name}</text>
                        {important ? (
                          <g>
                            <rect x={graph.layout.featureX + 136} y={y + 8} rx="10" width="34" height="20" fill="#10b981" fillOpacity="0.18" stroke="#34d399" />
                            <text x={graph.layout.featureX + 145} y={y + 21} fill="#a7f3d0" fontSize="10">FX</text>
                          </g>
                        ) : null}
                      </g>
                    );
                  })}

                  <g>
                    <rect x={graph.layout.selectionX} y={graph.layout.top} rx="16" width="132" height="36" fill="#132338" stroke="#21516d" />
                    <text x={graph.layout.selectionX + 12} y={graph.layout.top + 22} fill="#bae6fd" fontSize="12">Feature Selection</text>
                  </g>
                  <g>
                    <rect x={graph.layout.modelX} y={graph.layout.top} rx="16" width="132" height="36" fill="#132338" stroke="#21516d" />
                    <text x={graph.layout.modelX + 12} y={graph.layout.top + 22} fill="#bae6fd" fontSize="12">Model Training</text>
                  </g>
                  <g>
                    <rect x={graph.layout.explanationX} y={graph.layout.top} rx="16" width="110" height="36" fill="#132338" stroke="#21516d" />
                    <text x={graph.layout.explanationX + 12} y={graph.layout.top + 22} fill="#bae6fd" fontSize="12">SHAP / FI</text>
                  </g>
                </svg>
              </div>
            ) : null}
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
                    ["Feature Type", featureTypeLabel(selectedNode.featureType)],
                    ["Source Columns", selectedNode.source],
                    ["Generator", selectedNode.generator],
                    ["Formula", selectedNode.formula],
                    ["Human Meaning", featureMeaning(selectedNode)],
                    ["Status", selectedNode.selected ? "selected" : "dropped"],
                    ["Dropped Reason", selectedNode.droppedReason ?? "—"],
                    ["Importance", formatMetric(selectedNode.importance)],
                    ["SHAP Mean Abs", formatMetric(selectedNode.shap)],
                    ["Forecast Strategy", strategyLabel(selectedNode.forecastStrategy)],
                    ["Backtest Strategy", strategyLabel(selectedNode.backtestStrategy)],
                    ["Lifecycle", selectedNode.lifecycleTrail.length ? selectedNode.lifecycleTrail.join(" → ") : lifecycleLabel(selectedNode.lifecycle)]
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm dark:bg-[#0b1020]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                      <div className="mt-2 font-medium leading-6 text-slate-900 dark:text-white">{value}</div>
                    </div>
                  ))}
                </div>

                {selectedNode.modelIds.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {selectedNode.modelIds.map((modelId) => (
                      <Badge key={modelId} tone="good">{modelId}</Badge>
                    ))}
                  </div>
                ) : null}
              </>
            ) : (
              <div className="flex min-h-[320px] items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
                点击左侧任意 feature 节点后，这里会显示 Feature Detail。
              </div>
            )}
          </div>
        </div>

        {target.selection ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-950 dark:text-white">Feature Selection</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Generated {target.selection.generatedCount} → Selected {target.selection.selectedCount} → Dropped {target.selection.droppedCount}
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
