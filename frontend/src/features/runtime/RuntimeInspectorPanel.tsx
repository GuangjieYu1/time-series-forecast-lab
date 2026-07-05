import { useEffect, useMemo, useState } from "react";
import { Badge, SectionCard, Tabs, surface } from "../../shared/components/Ui";
import type {
  FeatureStepStatus,
  RuntimeFeatureNode,
  RuntimeFeaturePipelineTarget,
  RuntimeModelConsole,
  RuntimeOptimizationState,
  RuntimeRunDetail,
  RuntimeStepStatus
} from "../../shared/types/api";

type RuntimeTab = "console" | "pipeline" | "optimization" | "timeline";

function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "-";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const rest = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${rest}s`;
  const hours = Math.floor(minutes / 60);
  const minuteRest = minutes % 60;
  return `${hours}h ${minuteRest}m`;
}

function formatMetric(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleTimeString();
}

function modelKey(model: Pick<RuntimeModelConsole, "targetColumn" | "modelId">) {
  return `${model.targetColumn}:${model.modelId}`;
}

function runtimeStatusTone(status: RuntimeRunDetail["status"] | RuntimeModelConsole["status"] | RuntimeOptimizationState["status"]): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "completed" || status === "success") return "good";
  if (status === "failed") return "bad";
  if (status === "running" || status === "fitting" || status === "predicting" || status === "tuning" || status === "scoring") return "info";
  if (status === "idle" || status === "queued") return "neutral";
  return "warn";
}

function runtimeStatusLabel(status: RuntimeRunDetail["status"] | RuntimeModelConsole["status"] | RuntimeOptimizationState["status"]) {
  return {
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    queued: "排队中",
    tuning: "自动优化",
    fitting: "训练中",
    predicting: "预测中",
    scoring: "残差分析",
    success: "完成",
    idle: "待开始"
  }[status] ?? String(status);
}

function stepTone(status: FeatureStepStatus) {
  if (status === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200";
  if (status === "running") return "border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200";
  if (status === "failed") return "border-red-200 bg-red-50 text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200";
  return "border-slate-200 bg-slate-50 text-slate-500 dark:border-white/10 dark:bg-[#111827] dark:text-slate-400";
}

function familyTone(node: Pick<RuntimeFeatureNode, "lifecycle">) {
  if (node.lifecycle === "important") return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-400/20 dark:bg-fuchsia-400/10 dark:text-fuchsia-200";
  if (node.lifecycle === "used" || node.lifecycle === "selected") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200";
  if (node.lifecycle === "dropped") return "border-slate-200 bg-slate-50 text-slate-500 dark:border-white/10 dark:bg-[#111827] dark:text-slate-400";
  return "border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200";
}

function lifecycleLabel(lifecycle: RuntimeFeatureNode["lifecycle"]) {
  return {
    generated: "Generated",
    selected: "Selected",
    dropped: "Dropped",
    used: "Used",
    important: "Important"
  }[lifecycle];
}

function timelineTone(entry: RuntimeRunDetail["timeline"][number]) {
  if (entry.level === "warn") return "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100";
  if (entry.level === "error") return "border-red-200 bg-red-50 text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200";
  if (entry.level === "success") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200";
  return stepTone(entry.status);
}

function trialStatusTone(status: "running" | "success" | "failed" | "pruned"): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "success") return "good";
  if (status === "failed") return "bad";
  if (status === "pruned") return "warn";
  return "info";
}

function trialStatusLabel(status: "running" | "success" | "failed" | "pruned") {
  return {
    running: "运行中",
    success: "成功",
    failed: "失败",
    pruned: "已剪枝"
  }[status];
}

function JsonBlock({ value }: { value: Record<string, unknown> | null | undefined }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function ResourceSummary({ runtime }: { runtime: RuntimeRunDetail }) {
  const resource = runtime.resources;
  return (
    <div className="grid gap-3 md:grid-cols-5">
      {[
        ["当前阶段", runtime.currentStageLabel],
        ["整体进度", `${runtime.overallPercent}%`],
        ["已运行", formatDuration(runtime.elapsedSeconds)],
        ["预计剩余", formatDuration(runtime.estimatedRemainingSeconds)],
        ["当前目标", runtime.currentTarget ?? (runtime.kind === "final" ? "最终预测" : "-")]
      ].map(([label, value]) => (
        <div key={label} className={`${surface.softPanel} p-4`}>
          <div className={`text-xs ${surface.mutedText}`}>{label}</div>
          <div className={`mt-2 text-lg font-semibold ${surface.strongText}`}>{value}</div>
        </div>
      ))}
      {resource ? (
        <div className="md:col-span-5 grid gap-3 md:grid-cols-5">
          {[
            ["设备", resource.device.toUpperCase()],
            ["CPU", resource.cpuPercent === null ? "-" : `${resource.cpuPercent.toFixed(0)}%`],
            ["内存占用", resource.memoryUsedMb === null ? "-" : `${resource.memoryUsedMb.toFixed(0)} MB`],
            ["线程", resource.threadCount === null ? "-" : String(resource.threadCount)],
            ["GPU", resource.gpuLabel ?? "-"]
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-[#151b2e]">
              <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
              <div className="mt-2 font-medium text-slate-900 dark:text-white">{value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ConsoleView({
  runtime,
  selectedModelKey,
  onSelectModel
}: {
  runtime: RuntimeRunDetail;
  selectedModelKey: string;
  onSelectModel: (key: string) => void;
}) {
  const selectedModel = runtime.models.find((model) => modelKey(model) === selectedModelKey) ?? runtime.models[0] ?? null;
  return (
    <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
      <div className="space-y-3">
        {runtime.models.map((model) => {
          const active = modelKey(model) === modelKey(selectedModel ?? model);
          return (
            <button
              key={modelKey(model)}
              type="button"
              onClick={() => onSelectModel(modelKey(model))}
              className={`w-full rounded-2xl border p-3 text-left transition ${
                active
                  ? "border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10"
                  : "border-slate-200 bg-white hover:border-slate-300 dark:border-white/10 dark:bg-[#151b2e]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-950 dark:text-white">{model.modelName}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {model.targetColumn} · {model.computeTarget.toUpperCase()}
                  </div>
                </div>
                <Badge tone={runtimeStatusTone(model.status)}>{runtimeStatusLabel(model.status)}</Badge>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400" style={{ width: `${model.progressPercent}%` }} />
              </div>
              <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                {model.progressPercent}% · {model.message}
              </div>
            </button>
          );
        })}
      </div>

      {selectedModel ? (
        <div className="space-y-4">
          <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-slate-950 dark:text-white">{selectedModel.modelName}</div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  目标列：{selectedModel.targetColumn} · 当前阶段：{selectedModel.currentStage}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge tone={runtimeStatusTone(selectedModel.status)}>{runtimeStatusLabel(selectedModel.status)}</Badge>
                <Badge tone={selectedModel.computeTarget === "gpu" ? "warn" : "info"}>{selectedModel.computeTarget.toUpperCase()}</Badge>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-4">
              {[
                ["进度", `${selectedModel.progressPercent}%`],
                ["已运行", formatDuration(selectedModel.elapsedSeconds)],
                ["预计总时长", formatDuration(selectedModel.estimatedSeconds)],
                ["预计剩余", formatDuration(selectedModel.estimatedRemainingSeconds)]
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl bg-slate-50 p-3 text-sm dark:bg-[#0b1020]">
                  <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                  <div className="mt-2 font-semibold text-slate-900 dark:text-white">{value}</div>
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200">
              {selectedModel.message}
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-4">
              {[
                ["调参耗时", formatDuration(selectedModel.tuningSeconds)],
                ["训练耗时", formatDuration(selectedModel.fitSeconds)],
                ["预测耗时", formatDuration(selectedModel.predictSeconds)],
                ["线程", selectedModel.resource?.threadCount === null || selectedModel.resource?.threadCount === undefined ? "-" : String(selectedModel.resource.threadCount)]
              ].map(([label, value]) => (
                <div key={label} className="min-w-0 break-words rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-white/10">
                  <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                  <div className="mt-2 font-medium text-slate-900 dark:text-white">{value}</div>
                </div>
              ))}
            </div>
          </div>

          {selectedModel.optimization ? (
            <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-slate-950 dark:text-white">Optimization Console</div>
                <Badge tone={runtimeStatusTone(selectedModel.optimization.status)}>{runtimeStatusLabel(selectedModel.optimization.status)}</Badge>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-4">
                {[
                  ["策略", selectedModel.optimization.strategyLabel],
                  ["Sampler", selectedModel.optimization.sampler ?? "-"],
                  ["Pruner", selectedModel.optimization.pruner ?? "-"],
                  ["Trial", `${selectedModel.optimization.currentTrial}/${selectedModel.optimization.totalTrials}`],
                  ["当前 MAE", formatMetric(selectedModel.optimization.currentMetric)],
                  ["最佳 MAE", formatMetric(selectedModel.optimization.bestMetric)],
                  ["最新消息", selectedModel.optimization.lastMessage ?? "-"],
                  ["状态", runtimeStatusLabel(selectedModel.optimization.status)]
                ].map(([label, value]) => (
                  <div key={label} className="rounded-2xl bg-slate-50 p-3 text-sm dark:bg-[#0b1020]">
                    <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                    <div className="mt-2 font-medium text-slate-900 dark:text-white">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Selected Params</div>
                <JsonBlock value={selectedModel.optimization.selectedParams} />
              </div>
            </div>
          ) : null}

          {selectedModel.error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200">
              {selectedModel.error}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PipelineView({
  targets,
  selectedTarget,
  onSelectTarget
}: {
  targets: RuntimeFeaturePipelineTarget[];
  selectedTarget: string;
  onSelectTarget: (targetColumn: string) => void;
}) {
  const target = targets.find((item) => item.targetColumn === selectedTarget) ?? targets[0] ?? null;
  const [selectedNodeId, setSelectedNodeId] = useState("");

  useEffect(() => {
    if (!target?.lineage.length) return;
    if (!selectedNodeId || !target.lineage.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(target.lineage.find((node) => node.family !== "target")?.id ?? target.lineage[0].id);
    }
  }, [selectedNodeId, target]);

  const selectedNode = target?.lineage.find((node) => node.id === selectedNodeId) ?? target?.lineage[0] ?? null;
  const familySections = useMemo(() => {
    const familyOrder = new Map(target?.families.map((family, index) => [family.id, index]) ?? []);
    const rank = { important: 0, selected: 1, used: 2, generated: 3, dropped: 4 } satisfies Record<RuntimeFeatureNode["lifecycle"], number>;
    const groups = new Map<string, RuntimeFeatureNode[]>();
    (target?.lineage ?? [])
      .filter((node) => node.family !== "target")
      .forEach((node) => {
        groups.set(node.family, [...(groups.get(node.family) ?? []), node]);
      });
    return Array.from(groups.entries())
      .sort((a, b) => (familyOrder.get(a[0] as never) ?? 99) - (familyOrder.get(b[0] as never) ?? 99))
      .map(([family, nodes]) => [
        family,
        [...nodes].sort((a, b) => rank[a.lifecycle] - rank[b.lifecycle] || a.name.localeCompare(b.name, "zh-CN"))
      ] as const);
  }, [target]);
  const lifecycleSummary = useMemo(() => {
    const counters = new Map<RuntimeFeatureNode["lifecycle"], number>();
    (target?.lineage ?? []).forEach((node) => {
      counters.set(node.lifecycle, (counters.get(node.lifecycle) ?? 0) + 1);
    });
    return (["generated", "selected", "used", "important", "dropped"] as const).map((key) => ({ key, count: counters.get(key) ?? 0 }));
  }, [target]);
  const sourceNodes = useMemo(() => {
    const sources = new Map<string, { id: string; name: string; hint: string }>();
    (target?.lineage ?? []).forEach((node) => {
      if (!sources.has(node.source)) {
        sources.set(node.source, {
          id: `${target?.targetColumn ?? "target"}:${node.source}`,
          name: node.source,
          hint: node.source === target?.targetColumn ? "Target Series" : node.source === "Date" ? "Calendar Source" : "Covariate Source"
        });
      }
    });
    return Array.from(sources.values());
  }, [target]);

  if (!target) {
    return <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">当前还没有可展示的 feature pipeline。</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {targets.map((item) => (
          <button
            key={item.targetColumn}
            type="button"
            onClick={() => onSelectTarget(item.targetColumn)}
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

      <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-950 dark:text-white">Pipeline Timeline</div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">这里把输入、输出、耗时与 warning 沿着整条特征工程链路展开。</div>
          </div>
          <Badge tone="info">{target.detectedFrequency ? `频率 ${target.detectedFrequency}` : "频率自动识别"}</Badge>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-5">
          {target.steps.map((step, index) => (
            <div key={step.id} className={`rounded-3xl border p-4 text-sm transition-transform hover:-translate-y-0.5 ${stepTone(step.status)}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] opacity-80">Step {index + 1}</div>
                  <div className="mt-1 text-base font-semibold">{step.label}</div>
                </div>
                <Badge tone={step.status === "completed" ? "good" : step.status === "running" ? "info" : step.status === "failed" ? "bad" : "neutral"}>
                  {step.status === "completed" ? "已完成" : step.status === "running" ? "进行中" : step.status === "failed" ? "失败" : "待开始"}
                </Badge>
              </div>
              <div className="mt-3 text-xs leading-6 opacity-90">
                <div>
                  <span className="font-semibold">输入：</span>
                  {step.inputSummary || "-"}
                </div>
                <div className="mt-2">
                  <span className="font-semibold">输出：</span>
                  {step.outputSummary || "-"}
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs opacity-80">
                <span>{formatDuration(step.elapsedSeconds)}</span>
                <span>{step.warnings.length ? `${step.warnings.length} warning` : "No warnings"}</span>
              </div>
              {step.warnings.length ? (
                <div className="mt-3 rounded-2xl bg-white/70 px-3 py-2 text-xs leading-6 text-amber-900 dark:bg-black/20 dark:text-amber-100">
                  {step.warnings.join("；")}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {target.families.map((family) => (
          <div key={family.id} className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-950 dark:text-white">{family.label}</div>
              <Badge tone={family.enabled ? "good" : "neutral"}>{family.enabled ? "启用" : "关闭"}</Badge>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
              {[
                ["Generated", family.generatedCount],
                ["Selected", family.selectedCount],
                ["Important", family.importantCount]
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl bg-slate-50 px-2 py-3 dark:bg-[#0b1020]">
                  <div className="text-slate-500 dark:text-slate-400">{label}</div>
                  <div className="mt-1 font-semibold text-slate-900 dark:text-white">{value}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        {lifecycleSummary.map((item) => (
          <div
            key={item.key}
            className={`rounded-2xl border px-4 py-3 text-sm ${familyTone({ lifecycle: item.key })}`}
          >
            <div className="text-xs font-semibold uppercase tracking-[0.12em]">{lifecycleLabel(item.key)}</div>
            <div className="mt-2 text-xl font-semibold">{item.count}</div>
          </div>
        ))}
      </div>

      <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-950 dark:text-white">Feature Lineage Graph</div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">点击任意特征节点，可查看来源、公式、生命周期以及被哪些模型消费。</div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            {(["generated", "selected", "used", "important", "dropped"] as const).map((lifecycle) => (
              <span
                key={lifecycle}
                className={`rounded-full border px-3 py-1 ${familyTone({ lifecycle })}`}
              >
                {lifecycleLabel(lifecycle)}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-[220px_220px_minmax(0,1fr)_320px]">
          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">Sources</div>
            <div className="mt-3 space-y-3">
              {sourceNodes.map((source) => (
                <div key={source.id} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-[#151b2e]">
                  <div className="font-medium text-slate-900 dark:text-white">{source.name}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{source.hint}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">Families</div>
            <div className="mt-3 space-y-3">
              {target.families.map((family) => (
                <button
                  key={family.id}
                  type="button"
                  onClick={() => {
                    const firstNode = familySections.find(([familyId]) => familyId === family.id)?.[1][0];
                    if (firstNode) setSelectedNodeId(firstNode.id);
                  }}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left transition hover:border-cyan-300 hover:bg-cyan-50 dark:border-white/10 dark:bg-[#151b2e] dark:hover:border-cyan-400/30 dark:hover:bg-cyan-400/10"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-slate-900 dark:text-white">{family.label}</div>
                    <span className="text-xs text-slate-500 dark:text-slate-400">{family.generatedCount}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    Selected {family.selectedCount} · Important {family.importantCount}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">Feature Nodes</div>
            <div className="mt-3 space-y-4">
              {familySections.map(([family, nodes]) => (
                <div key={family}>
                  <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                    <span>{target.families.find((item) => item.id === family)?.label ?? family}</span>
                    <span className="h-px flex-1 bg-slate-200 dark:bg-white/10" />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {nodes.map((node) => {
                      const active = node.id === selectedNode?.id;
                      return (
                        <button
                          key={node.id}
                          type="button"
                          onClick={() => setSelectedNodeId(node.id)}
                          className={`rounded-2xl border px-3 py-2 text-left text-sm transition hover:-translate-y-0.5 ${familyTone(node)} ${active ? "ring-2 ring-cyan-300 dark:ring-cyan-400/40" : ""}`}
                        >
                          <div className="font-medium">{node.name}</div>
                          <div className="mt-1 text-[11px] uppercase tracking-[0.12em] opacity-80">{lifecycleLabel(node.lifecycle)}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
            {selectedNode ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-lg font-semibold text-slate-950 dark:text-white">{selectedNode.name}</div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {selectedNode.source} → {target.families.find((family) => family.id === selectedNode.family)?.label ?? selectedNode.family}
                    </div>
                  </div>
                  <span className={`rounded-full border px-3 py-1 text-xs ${familyTone(selectedNode)}`}>{lifecycleLabel(selectedNode.lifecycle)}</span>
                </div>

                <div className="mt-4 grid gap-3">
                  {[
                    ["Formula", selectedNode.formula],
                    ["Status", lifecycleLabel(selectedNode.lifecycle)],
                    ["Importance", selectedNode.importance === null ? "尚未记录" : formatMetric(selectedNode.importance)],
                    ["SHAP", selectedNode.shap === null ? "尚未记录" : formatMetric(selectedNode.shap)],
                    ["Models", selectedNode.modelIds.length ? selectedNode.modelIds.join(", ") : "当前未绑定到具体模型"]
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm dark:bg-[#0b1020]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                      <div className="mt-2 font-medium text-slate-900 dark:text-white">{value}</div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="flex h-full min-h-[240px] items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">选择一个特征节点后，这里会显示它的 lineage 详情。</div>
            )}
          </div>
        </div>
      </div>

      {target.warnings.length ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
          {target.warnings.join("；")}
        </div>
      ) : null}
    </div>
  );
}

function OptimizationView({
  models,
  selectedKey,
  onSelect
}: {
  models: RuntimeOptimizationState[];
  selectedKey: string;
  onSelect: (key: string) => void;
}) {
  const selected = models.find((item) => `${item.targetColumn}:${item.modelId}` === selectedKey) ?? models[0] ?? null;
  const progressPercent = selected?.totalTrials ? Math.min(100, (selected.currentTrial / selected.totalTrials) * 100) : 0;
  const sortedSuccessfulTrials = useMemo(
    () =>
      [...(selected?.trials ?? [])]
        .filter((trial) => trial.status === "success" && trial.metric !== null)
        .sort((a, b) => (a.metric ?? Number.POSITIVE_INFINITY) - (b.metric ?? Number.POSITIVE_INFINITY)),
    [selected]
  );
  const bestTrial = (selected?.trials ?? []).find((trial) => trial.selected) ?? sortedSuccessfulTrials[0] ?? null;
  const latestTrial = selected?.trials[selected.trials.length - 1] ?? null;
  const firstSuccessfulTrial = sortedSuccessfulTrials.length ? selected?.trials.find((trial) => trial.status === "success" && trial.metric !== null) ?? null : null;
  const improvement =
    bestTrial && firstSuccessfulTrial && bestTrial.metric !== null && firstSuccessfulTrial.metric !== null
      ? firstSuccessfulTrial.metric - bestTrial.metric
      : null;
  const statusSummary = useMemo(() => {
    const counters = { running: 0, success: 0, failed: 0, pruned: 0 };
    (selected?.trials ?? []).forEach((trial) => {
      counters[trial.status] += 1;
    });
    return counters;
  }, [selected]);

  if (!selected) {
    return <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">当前没有优化轨迹。</div>;
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {models.map((model) => {
          const key = `${model.targetColumn}:${model.modelId}`;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onSelect(key)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                key === `${selected.targetColumn}:${selected.modelId}`
                  ? "border-cyan-300 bg-cyan-50 text-cyan-700 dark:border-cyan-400/30 dark:bg-cyan-400/10 dark:text-cyan-200"
                  : "border-slate-200 bg-white text-slate-600 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-300"
              }`}
            >
              {model.modelName} / {model.targetColumn}
            </button>
          );
        })}
      </div>

      <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-lg font-semibold text-slate-950 dark:text-white">{selected.modelName}</div>
            <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{selected.targetColumn} · {selected.strategyLabel}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={runtimeStatusTone(selected.status)}>{runtimeStatusLabel(selected.status)}</Badge>
            {selected.sampler ? <Badge tone="info">{selected.sampler}</Badge> : null}
            {selected.pruner ? <Badge tone="warn">{selected.pruner}</Badge> : null}
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-4 xl:grid-cols-8">
          {[
            ["Trial", `${selected.currentTrial}/${selected.totalTrials}`],
            ["最佳 MAE", formatMetric(selected.bestMetric)],
            ["当前 MAE", formatMetric(selected.currentMetric)],
            ["成功", String(statusSummary.success)],
            ["剪枝", String(statusSummary.pruned)],
            ["失败", String(statusSummary.failed)],
            ["Sampler", selected.sampler ?? "-"],
            ["Pruner", selected.pruner ?? "-"]
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm dark:bg-[#0b1020]">
              <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
              <div className="mt-2 font-semibold text-slate-900 dark:text-white">{value}</div>
            </div>
          ))}
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
            <span>Optimization Progress</span>
            <span>{progressPercent.toFixed(0)}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all" style={{ width: `${progressPercent}%` }} />
          </div>
          <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">{selected.lastMessage ?? "正在等待新的优化日志。"}</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        <div className="space-y-4">
          <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="text-sm font-semibold text-slate-950 dark:text-white">Best Trial Snapshot</div>
            <div className="mt-3 grid gap-3">
              {[
                ["Best Trial", bestTrial ? `#${bestTrial.trialNumber}` : "-"],
                ["Best MAE", bestTrial ? formatMetric(bestTrial.metric) : "-"],
                ["Latest Trial", latestTrial ? `#${latestTrial.trialNumber}` : "-"],
                ["MAE Improvement", improvement === null ? "-" : formatMetric(improvement)]
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm dark:bg-[#0b1020]">
                  <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
                  <div className="mt-2 font-medium text-slate-900 dark:text-white">{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Selected Params</div>
            <JsonBlock value={selected.selectedParams} />
          </div>

          {selected.warnings.length ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
              {selected.warnings.join("；")}
            </div>
          ) : null}
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm font-semibold text-slate-950 dark:text-white">Trials Leaderboard</div>
            {bestTrial ? <Badge tone="good">Best #{bestTrial.trialNumber}</Badge> : null}
          </div>

          {sortedSuccessfulTrials.length ? (
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              {sortedSuccessfulTrials.slice(0, 3).map((trial) => (
                <div key={trial.trialNumber} className={`rounded-2xl border px-4 py-3 text-sm ${trial.selected ? "border-emerald-300 bg-emerald-50 dark:border-emerald-400/20 dark:bg-emerald-400/10" : "border-slate-200 bg-slate-50 dark:border-white/10 dark:bg-[#0b1020]"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-slate-900 dark:text-white">Trial #{trial.trialNumber}</div>
                    <Badge tone={trialStatusTone(trial.status)}>{trial.selected ? "选中" : trialStatusLabel(trial.status)}</Badge>
                  </div>
                  <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">MAE</div>
                  <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{formatMetric(trial.metric)}</div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="mt-3 max-h-[420px] overflow-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                <tr>
                  <th className="pb-2 pr-3">#</th>
                  <th className="pb-2 pr-3">状态</th>
                  <th className="pb-2 pr-3">MAE</th>
                  <th className="pb-2 pr-3">耗时</th>
                  <th className="pb-2 pr-3">选中</th>
                  <th className="pb-2 pr-3">参数 / 备注</th>
                </tr>
              </thead>
              <tbody>
                {selected.trials.map((trial) => (
                  <tr
                    key={trial.trialNumber}
                    className={`border-t align-top dark:border-white/10 ${
                      trial.selected ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-400/20 dark:bg-emerald-400/5" : "border-slate-200"
                    }`}
                  >
                    <td className="py-3 pr-3 font-medium text-slate-900 dark:text-white">{trial.trialNumber}</td>
                    <td className="py-3 pr-3">
                      <Badge tone={trialStatusTone(trial.status)}>{trialStatusLabel(trial.status)}</Badge>
                    </td>
                    <td className="py-3 pr-3 text-slate-700 dark:text-slate-200">{formatMetric(trial.metric)}</td>
                    <td className="py-3 pr-3 text-slate-700 dark:text-slate-200">{formatDuration(trial.elapsedSeconds)}</td>
                    <td className="py-3 pr-3 text-slate-700 dark:text-slate-200">{trial.selected ? "是" : "否"}</td>
                    <td className="py-3 pr-3 text-xs leading-6 text-slate-600 dark:text-slate-300">
                      <div>{JSON.stringify(trial.params)}</div>
                      {trial.message ? <div className="mt-1 text-slate-500 dark:text-slate-400">{trial.message}</div> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function TimelineView({ runtime }: { runtime: RuntimeRunDetail }) {
  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
        <div className="text-sm font-semibold text-slate-950 dark:text-white">Runtime Timeline</div>
        <div className="mt-3 max-h-[520px] space-y-3 overflow-y-auto overflow-x-hidden">
          {runtime.timeline.map((entry) => (
            <div key={entry.id} className={`min-w-0 break-words rounded-2xl border px-4 py-3 text-sm ${timelineTone(entry)}`}>
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium">{entry.label}</div>
                <div className="text-xs">{formatTimestamp(entry.timestamp)}</div>
              </div>
              <div className="mt-2 text-xs leading-6">
                {entry.message ?? "-"}
                {entry.modelName ? ` · ${entry.modelName}` : ""}
                {entry.targetColumn ? ` · ${entry.targetColumn}` : ""}
                {entry.overallPercent !== null ? ` · ${entry.overallPercent}%` : ""}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
        <div className="text-sm font-semibold text-slate-950 dark:text-white">Live Log</div>
        <div className="mt-3 max-h-[520px] space-y-3 overflow-y-auto overflow-x-hidden">
          {runtime.logs.map((entry) => (
            <div key={entry.id} className="min-w-0 break-words rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-white/10">
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={entry.level === "success" ? "good" : entry.level === "error" ? "bad" : entry.level === "warn" ? "warn" : "info"}>
                    {entry.stage}
                  </Badge>
                  {entry.modelName ? <span className="font-medium text-slate-900 dark:text-white">{entry.modelName}</span> : null}
                  {entry.targetColumn ? <span className="text-slate-500 dark:text-slate-400">{entry.targetColumn}</span> : null}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">{formatTimestamp(entry.timestamp)}</div>
              </div>
              <div className="mt-2 leading-6 text-slate-700 dark:text-slate-200">{entry.message}</div>
              {entry.metricLabel ? (
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {entry.metricLabel}: {formatMetric(entry.metricValue)}
                </div>
              ) : null}
              {Object.keys(entry.params).length ? (
                <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-[#0b1020] dark:text-slate-300">
                  {JSON.stringify(entry.params)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function RuntimeInspectorPanel({
  runtime,
  title = "Transparent Experiment Engine",
  description = "把模型执行控制台、特征管线、优化过程与时间线放在同一处查看。",
  className = ""
}: {
  runtime: RuntimeRunDetail | null;
  title?: string;
  description?: string;
  className?: string;
}) {
  const [tab, setTab] = useState<RuntimeTab>("console");
  const [selectedModelKey, setSelectedModelKey] = useState("");
  const [selectedTarget, setSelectedTarget] = useState("");
  const [selectedOptimizationKey, setSelectedOptimizationKey] = useState("");

  useEffect(() => {
    if (!runtime?.models.length) return;
    if (!selectedModelKey || !runtime.models.some((model) => modelKey(model) === selectedModelKey)) {
      setSelectedModelKey(modelKey(runtime.models[0]));
    }
  }, [runtime, selectedModelKey]);

  useEffect(() => {
    if (!runtime?.featurePipeline.length) return;
    if (!selectedTarget || !runtime.featurePipeline.some((target) => target.targetColumn === selectedTarget)) {
      setSelectedTarget(runtime.featurePipeline[0].targetColumn);
    }
  }, [runtime, selectedTarget]);

  useEffect(() => {
    if (!runtime?.optimization.length) return;
    if (!selectedOptimizationKey || !runtime.optimization.some((item) => `${item.targetColumn}:${item.modelId}` === selectedOptimizationKey)) {
      setSelectedOptimizationKey(`${runtime.optimization[0].targetColumn}:${runtime.optimization[0].modelId}`);
    }
  }, [runtime, selectedOptimizationKey]);

  if (!runtime) {
    return (
      <SectionCard title={title} description={description} className={className}>
        <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-sm leading-7 text-slate-500 dark:border-white/10 dark:text-slate-400">
          当前这条历史记录还没有可回放的透明引擎快照。
          <div className="mt-2 text-xs leading-6">
            常见原因有两种：一是实验创建于透明引擎落库之前；二是这次运行只保存了排行榜/预测结果，没有保存 runtime 轨迹。
          </div>
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title={title}
      description={description}
      className={className}
      action={
        <div className="flex flex-wrap gap-2">
          <Badge tone={runtimeStatusTone(runtime.status)}>{runtimeStatusLabel(runtime.status)}</Badge>
          <Badge tone={runtime.kind === "final" ? "warn" : "info"}>{runtime.kind === "final" ? "Final Forecast" : "Backtest"}</Badge>
        </div>
      }
    >
      <div className="space-y-5">
        <ResourceSummary runtime={runtime} />

        <div className="grid gap-2 md:grid-cols-5">
          {runtime.stateMachine.map((step) => (
            <div key={step.id} className={`rounded-2xl border px-3 py-3 text-sm ${stepTone(step.status)}`}>
              <div className="text-xs font-semibold uppercase tracking-[0.12em]">{step.label}</div>
              <div className="mt-2">{step.status === "running" ? "进行中" : step.status === "completed" ? "已完成" : step.status === "failed" ? "失败" : "待开始"}</div>
              <div className="mt-1 text-xs opacity-80">{formatDuration(step.elapsedSeconds)}</div>
            </div>
          ))}
        </div>

        <Tabs<RuntimeTab>
          value={tab}
          onChange={setTab}
          items={[
            { id: "console", label: "Model Console" },
            { id: "pipeline", label: "Feature Pipeline" },
            { id: "optimization", label: "Optimization" },
            { id: "timeline", label: "Timeline & Logs" }
          ]}
        />

        {tab === "console" ? <ConsoleView runtime={runtime} selectedModelKey={selectedModelKey} onSelectModel={setSelectedModelKey} /> : null}
        {tab === "pipeline" ? <PipelineView targets={runtime.featurePipeline} selectedTarget={selectedTarget} onSelectTarget={setSelectedTarget} /> : null}
        {tab === "optimization" ? <OptimizationView models={runtime.optimization} selectedKey={selectedOptimizationKey} onSelect={setSelectedOptimizationKey} /> : null}
        {tab === "timeline" ? <TimelineView runtime={runtime} /> : null}
      </div>
    </SectionCard>
  );
}
