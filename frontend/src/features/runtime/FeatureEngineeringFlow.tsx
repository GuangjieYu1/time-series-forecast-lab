import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Badge } from "../../shared/components/Ui";
import type {
  FeatureStepStatus,
  RuntimeFeatureDataProfile,
  RuntimeFeaturePipelineStep,
  RuntimeFeaturePipelineTarget
} from "../../shared/types/api";

const statusMeta: Record<FeatureStepStatus, { label: string; tone: "neutral" | "good" | "warn" | "bad" | "info"; className: string }> = {
  pending: {
    label: "等待",
    tone: "neutral",
    className: "border-slate-200 bg-slate-50 text-slate-500 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-400"
  },
  running: {
    label: "运行中",
    tone: "info",
    className: "border-cyan-300 bg-cyan-50 text-cyan-800 shadow-[0_0_22px_rgba(34,211,238,0.16)] dark:border-cyan-400/40 dark:bg-cyan-400/10 dark:text-cyan-100"
  },
  completed: {
    label: "完成",
    tone: "good",
    className: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-100"
  },
  skipped: {
    label: "跳过",
    tone: "neutral",
    className: "border-slate-200 bg-slate-100/70 text-slate-400 opacity-75 dark:border-white/10 dark:bg-white/5 dark:text-slate-500"
  },
  failed: {
    label: "失败",
    tone: "bad",
    className: "border-red-300 bg-red-50 text-red-800 dark:border-red-400/30 dark:bg-red-400/10 dark:text-red-100"
  }
};

const fallbackStepDescriptions: Record<string, string> = {
  source_alignment: "校验目标时间与数值是否一一对应，并按时间顺序整理输入序列。",
  covariate_loader: "载入用户选择的协变量，并按目标时间轴完成对齐和缺失处理。",
  calendar_generator: "从时间戳生成小时、星期、月份等日历特征。",
  holiday_generator: "生成节假日及节假日前后等业务日历特征。",
  lag_generator: "仅使用历史观测生成滞后特征，帮助模型学习过去值的影响。",
  rolling_generator: "基于历史窗口生成滚动均值、波动率等统计特征。",
  feature_merge: "把目标、协变量和生成特征合并成统一训练矩阵。",
  leakage_guard: "检查并阻止使用预测时点之后的信息，降低数据泄漏风险。",
  feature_selection: "根据有效性和模型能力保留可用于训练的特征。",
  matrix_ready: "冻结最终特征列顺序和数据类型，供各模型共享使用。"
};

function stepDescription(step: RuntimeFeaturePipelineStep) {
  return step.description || fallbackStepDescriptions[step.id] || "执行该阶段的数据处理并记录输入、输出与告警。";
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "-";
  if (seconds < 0.001) return "<1ms";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  return `${seconds.toFixed(seconds < 10 ? 2 : 1)}s`;
}

function formatBytes(value: number) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatNumber(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return value.toFixed(Math.abs(value) < 1 ? 4 : 2);
}

function resolvedStep(step: RuntimeFeaturePipelineStep, playbackIndex: number | null): RuntimeFeaturePipelineStep {
  if (playbackIndex === null || step.sequence <= playbackIndex + 1) return step;
  return {
    ...step,
    status: "pending",
    progressPercent: 0,
    startedAt: null,
    finishedAt: null,
    outputSummary: "",
    outputProfile: null,
    elapsedSeconds: null,
    warnings: [],
    error: null
  };
}

function ProfileSummary({ profile }: { profile: RuntimeFeatureDataProfile | null }) {
  if (!profile) return <div className="text-xs text-slate-400">暂无统计快照</div>;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        {[
          ["行", profile.rowCount.toLocaleString()],
          ["列", profile.columnCount.toLocaleString()],
          ["缺失", profile.missingValueCount.toLocaleString()],
          ["内存", formatBytes(profile.memoryBytes)]
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg bg-slate-100 px-3 py-2 dark:bg-white/5">
            <div className="text-slate-400">{label}</div>
            <div className="mt-1 font-semibold text-slate-900 dark:text-white">{value}</div>
          </div>
        ))}
      </div>
      {profile.columnProfiles.length ? (
        <div className="max-h-44 overflow-auto rounded-lg border border-slate-200 dark:border-white/10">
          <table className="w-full min-w-[520px] text-left text-xs">
            <thead className="sticky top-0 bg-slate-50 text-slate-500 dark:bg-[#111827] dark:text-slate-400">
              <tr><th className="px-3 py-2">特征</th><th>最小值</th><th>均值</th><th>最大值</th><th>标准差</th><th>缺失</th></tr>
            </thead>
            <tbody>
              {profile.columnProfiles.map((column) => (
                <tr key={column.name} className="border-t border-slate-100 dark:border-white/5">
                  <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-200">{column.name}</td>
                  <td>{formatNumber(column.minimum)}</td><td>{formatNumber(column.mean)}</td><td>{formatNumber(column.maximum)}</td><td>{formatNumber(column.std)}</td><td>{column.nullCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function StepAnimation({ step }: { step: RuntimeFeaturePipelineStep }) {
  const visualization = step.visualization;
  const [markerIndex, setMarkerIndex] = useState(0);
  const markers = visualization?.markers ?? [];
  useEffect(() => {
    if (step.id !== "holiday_generator" || markers.length < 2) return;
    const timer = window.setInterval(() => setMarkerIndex((value) => (value + 1) % markers.length), 900);
    return () => window.clearInterval(timer);
  }, [markers.length, step.id]);
  const values = (visualization?.sampleValues ?? []).slice(0, 16);
  const bars = values.length ? values : [2, 5, 3, 7, 4, 8, 6, 9];
  const minimum = Math.min(...bars);
  const span = Math.max(Math.max(...bars) - minimum, 1);
  const barChart = <div className="flex h-16 items-end gap-1.5">{bars.map((value, index) => <span key={index} className="feature-flow-bar flex-1 rounded-t bg-cyan-400/70" style={{ height: `${22 + ((value - minimum) / span) * 70}%`, animationDelay: `${index * 90}ms` }} />)}</div>;
  if (step.id === "holiday_generator") {
    const start = visualization?.timeStart ? Date.parse(visualization.timeStart) : 0;
    const end = visualization?.timeEnd ? Date.parse(visualization.timeEnd) : start + 1;
    return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">
      <div className="flex justify-between text-[10px] text-slate-400"><span>{visualization?.timeStart?.slice(0, 10) ?? "开始"}</span><span>{visualization?.timeEnd?.slice(0, 10) ?? "结束"}</span></div>
      <div className="relative mt-4 h-8"><div className="absolute left-0 right-0 top-3 h-px bg-slate-300 dark:bg-white/20" />{markers.map((marker, index) => { const position = Math.max(0, Math.min(100, ((Date.parse(marker.time) - start) / Math.max(end - start, 1)) * 100)); const active = index === markerIndex; return <span key={`${marker.time}-${index}`} title={`${marker.time} ${marker.label}`} className={`absolute top-1 h-5 w-1.5 -translate-x-1/2 rounded-full transition-all ${active ? "feature-holiday-active bg-amber-400" : "bg-indigo-400/60"}`} style={{ left: `${position}%` }} />; })}</div>
      <div className="mt-1 min-h-5 text-xs text-amber-600 dark:text-amber-300">{markers.length ? `${markers[markerIndex]?.time} · ${markers[markerIndex]?.label}` : "当前数据区间没有节假日"}</div>
    </div>;
  }
  const visualByStep: Record<string, ReactNode> = {
    source_alignment: <div className="flex h-16 items-center justify-around">{[4, 1, 5, 2, 3].map((value, index) => <span key={value} className="feature-align-dot flex h-8 w-8 items-center justify-center rounded-full bg-indigo-500/15 text-xs text-indigo-500" style={{ animationDelay: `${index * 120}ms` }}>{value}</span>)}</div>,
    covariate_loader: <div className="space-y-2 py-2">{["静态", "未来已知", "未来未知"].map((label, index) => <div key={label} className="flex items-center gap-2 text-[11px]"><span className="w-16 text-slate-400">{label}</span><span className="h-1 flex-1 overflow-hidden rounded bg-slate-200 dark:bg-white/10"><span className="feature-flow-stream block h-full w-1/3 rounded bg-cyan-400" style={{ animationDelay: `${index * 250}ms` }} /></span></div>)}</div>,
    calendar_generator: <div className="grid h-16 grid-cols-7 gap-1">{Array.from({ length: 21 }, (_, index) => <span key={index} className="feature-calendar-cell rounded bg-indigo-400/15" style={{ animationDelay: `${index * 45}ms` }} />)}</div>,
    lag_generator: <div className="relative h-16">{[0, 1, 2, 3, 4, 5, 6].map((index) => <span key={index} className="feature-lag-dot absolute top-6 h-3 w-3 rounded-full bg-cyan-400" style={{ left: `${index * 14}%`, animationDelay: `${index * 90}ms` }} />)}</div>,
    rolling_generator: <div className="relative h-16">{barChart}<span className="feature-rolling-window absolute bottom-0 top-0 w-1/3 rounded border-2 border-amber-400/80 bg-amber-300/10" /></div>,
    feature_merge: <div className="relative h-16"><span className="absolute left-3 top-1 h-2 w-2 rounded-full bg-indigo-400" /><span className="absolute left-3 top-7 h-2 w-2 rounded-full bg-cyan-400" /><span className="absolute left-3 top-12 h-2 w-2 rounded-full bg-emerald-400" /><span className="feature-merge-node absolute right-5 top-6 h-5 w-5 rounded-md bg-indigo-500" /><div className="absolute left-6 right-8 top-8 h-px bg-gradient-to-r from-cyan-400 via-indigo-400 to-indigo-500" /></div>,
    leakage_guard: <div className="relative h-16">{barChart}<span className="absolute bottom-0 right-1/3 top-0 w-px bg-red-400" /><span className="feature-leak-block absolute right-3 top-5 rounded bg-red-400/15 px-2 py-1 text-[10px] text-red-500">未来值已拦截</span></div>,
    feature_selection: <div className="flex h-16 flex-wrap content-center gap-2">{["lag_1", "month", "缺失过多", "低重要性"].map((label, index) => <span key={label} className={`feature-selection-chip rounded-full px-2 py-1 text-[10px] ${index < 2 ? "bg-emerald-400/15 text-emerald-500" : "bg-slate-400/15 text-slate-400 line-through"}`} style={{ animationDelay: `${index * 160}ms` }}>{label}</span>)}</div>,
    matrix_ready: <div className="grid h-16 grid-cols-8 gap-1">{Array.from({ length: 32 }, (_, index) => <span key={index} className="feature-matrix-cell rounded-sm bg-cyan-400/30" style={{ animationDelay: `${index * 35}ms` }} />)}</div>
  };
  return <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">{visualByStep[step.id] ?? barChart}</div>;
}
function StepNode({ step, active, onClick }: { step: RuntimeFeaturePipelineStep; active: boolean; onClick: () => void }) {
  const meta = statusMeta[step.status];
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-[96px] w-full rounded-xl border p-3 text-left transition ${meta.className} ${active ? "ring-2 ring-indigo-400/60" : "hover:-translate-y-0.5"}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase text-current/60">Step {step.sequence}</div>
          <div className="mt-1 flex items-center gap-2 text-sm font-semibold">
            <span>{step.label}</span>
            <span
              className="inline-flex h-4 w-4 shrink-0 cursor-help items-center justify-center rounded-full bg-slate-400/20 text-[10px] font-semibold text-slate-500 dark:bg-white/10 dark:text-slate-400"
              title={stepDescription(step)}
              aria-label={`${step.label} 作用说明`}
              tabIndex={0}
            >
              i
            </span>
          </div>
        </div>
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </div>
      <div className="mt-3 flex items-center justify-between text-[11px] opacity-75">
        <span>{step.generatedFeatures.length ? `${step.generatedFeatures.length} 个特征` : step.machineId ? "生成器" : "流程"}</span>
        <span>{formatDuration(step.elapsedSeconds)}</span>
      </div>
    </button>
  );
}

function FlowArrow({ active = false }: { active?: boolean }) {
  return (
    <div className="flex h-7 items-center justify-center" aria-hidden="true">
      <div className={`h-full w-px ${active ? "bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.8)]" : "bg-slate-200 dark:bg-white/10"}`} />
    </div>
  );
}

export function FeatureEngineeringFlow({
  targets,
  mode = "live",
  compact = false
}: {
  targets: RuntimeFeaturePipelineTarget[];
  mode?: "live" | "history";
  compact?: boolean;
}) {
  const [selectedTarget, setSelectedTarget] = useState(targets[0]?.targetColumn ?? "");
  const target = targets.find((item) => item.targetColumn === selectedTarget) ?? targets[0] ?? null;
  const [selectedStepId, setSelectedStepId] = useState("");
  const [expanded, setExpanded] = useState(!compact);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [playbackIndex, setPlaybackIndex] = useState<number | null>(mode === "history" ? Math.max((target?.steps.length ?? 1) - 1, 0) : null);

  useEffect(() => {
    if (!targets.some((item) => item.targetColumn === selectedTarget)) setSelectedTarget(targets[0]?.targetColumn ?? "");
  }, [selectedTarget, targets]);

  useEffect(() => {
    if (!target) return;
    const preferred = target.currentStepId ?? [...target.steps].reverse().find((step) => step.status !== "pending")?.id ?? target.steps[0]?.id ?? "";
    if (!selectedStepId || !target.steps.some((step) => step.id === selectedStepId)) setSelectedStepId(preferred);
    if (mode === "history" && playbackIndex !== null && playbackIndex >= target.steps.length) setPlaybackIndex(Math.max(target.steps.length - 1, 0));
  }, [mode, playbackIndex, selectedStepId, target]);

  useEffect(() => {
    if (mode !== "history" || !playing || !target) return;
    const timer = window.setInterval(() => {
      setPlaybackIndex((current) => {
        const next = (current ?? -1) + 1;
        if (next >= target.steps.length - 1) {
          setPlaying(false);
          return Math.max(target.steps.length - 1, 0);
        }
        return next;
      });
    }, 900 / speed);
    return () => window.clearInterval(timer);
  }, [mode, playing, speed, target]);

  const visibleSteps = useMemo(
    () => (target?.steps ?? []).map((step) => resolvedStep(step, mode === "history" ? playbackIndex : null)),
    [mode, playbackIndex, target]
  );
  const selectedStep = visibleSteps.find((step) => step.id === selectedStepId) ?? visibleSteps[0] ?? null;
  const sourceStep = visibleSteps.find((step) => step.id === "source_alignment") ?? visibleSteps[0] ?? null;
  const generatorSteps = visibleSteps.filter((step) => Boolean(step.machineId));
  const trunkSteps = visibleSteps.filter((step) => step !== sourceStep && !step.machineId);
  const hasRunningStep = visibleSteps.some((step) => step.status === "running");

  if (!target) return null;

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-white/10 dark:bg-[#111827]">
      <div className="border-b border-slate-200 px-4 py-4 dark:border-white/10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-950 dark:text-white">特征工程流程</div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">真实步骤事件、统计元数据与共享矩阵状态</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={target.status === "failed" ? "bad" : target.status === "completed" ? "good" : "info"}>{target.progressPercent}%</Badge>
            <Badge tone={target.traceMode === "legacy_inferred" ? "warn" : "info"}>{target.traceMode === "legacy_inferred" ? "历史推导" : "真实事件"}</Badge>
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:border-slate-300 dark:border-white/10 dark:text-slate-300 dark:hover:border-white/20"
            >
              <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
              {expanded ? "收起" : "展开"}
            </button>
          </div>
        </div>
        {targets.length > 1 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {targets.map((item) => (
              <button key={item.targetColumn} type="button" onClick={() => setSelectedTarget(item.targetColumn)} className={`rounded-lg border px-3 py-1.5 text-xs ${item.targetColumn === target.targetColumn ? "border-indigo-400 bg-indigo-50 text-indigo-700 dark:bg-indigo-400/10 dark:text-indigo-200" : "border-slate-200 text-slate-500 dark:border-white/10 dark:text-slate-400"}`}>
                {item.targetColumn}
              </button>
            ))}
          </div>
        ) : null}
        {mode === "history" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => { if (!playing && playbackIndex === target.steps.length - 1) setPlaybackIndex(-1); setPlaying((value) => !value); }} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 dark:border-white/10 dark:text-slate-200">{playing ? "暂停" : "播放"}</button>
            {[0.5, 1, 2].map((value) => <button key={value} type="button" onClick={() => setSpeed(value)} className={`rounded-lg px-2 py-1 text-xs ${speed === value ? "bg-indigo-500 text-white" : "bg-slate-100 text-slate-500 dark:bg-white/5 dark:text-slate-400"}`}>{value}x</button>)}
            <input aria-label="回放进度" className="min-w-[180px] flex-1 accent-indigo-500" type="range" min={-1} max={Math.max(target.steps.length - 1, 0)} value={playbackIndex ?? target.steps.length - 1} onChange={(event) => { setPlaying(false); setPlaybackIndex(Number(event.target.value)); }} />
          </div>
        ) : null}
        {target.traceMode === "legacy_inferred" ? <div className="mt-3 text-xs text-amber-600 dark:text-amber-300">该实验早于逐步追踪能力，当前流程由历史配置推导，不包含真实步骤耗时。</div> : null}
      </div>

      {expanded ? (
        compact ? (
          <div className="space-y-4 p-4">
            <div className="flex gap-2 overflow-x-auto pb-1">
              {visibleSteps.map((step) => {
                const meta = statusMeta[step.status];
                return (
                  <button
                    key={step.id}
                    type="button"
                    onClick={() => setSelectedStepId(step.id)}
                    className={`min-w-[170px] flex-none rounded-xl border p-3 text-left transition ${meta.className} ${selectedStep?.id === step.id ? "ring-2 ring-indigo-400/60" : "hover:-translate-y-0.5"}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-[10px] font-semibold uppercase text-current/60">Step {step.sequence}</div>
                        <div className="mt-1 truncate text-sm font-semibold">{step.label}</div>
                      </div>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                    </div>
                    <div className="mt-3 flex items-center justify-between text-[11px] opacity-75">
                      <span>{step.progressPercent}%</span>
                      <span>{formatDuration(step.elapsedSeconds)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
            {hasRunningStep ? <div className="h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10"><div className="h-full w-1/3 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400" /></div> : null}
            {selectedStep ? (
              <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
                <div className="space-y-3">
                  <StepAnimation step={selectedStep} />
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-lg bg-slate-50 p-3 dark:bg-[#0b1020]"><div className="text-slate-400">进度</div><div className="mt-1 font-semibold text-slate-900 dark:text-white">{selectedStep.progressPercent}%</div></div>
                    <div className="rounded-lg bg-slate-50 p-3 dark:bg-[#0b1020]"><div className="text-slate-400">耗时</div><div className="mt-1 font-semibold text-slate-900 dark:text-white">{formatDuration(selectedStep.elapsedSeconds)}</div></div>
                  </div>
                </div>
                <div className="space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-xs text-slate-400">步骤 {selectedStep.sequence}</div>
                      <div className="mt-1 font-semibold text-slate-950 dark:text-white">{selectedStep.label}</div>
                    </div>
                    <Badge tone={statusMeta[selectedStep.status].tone}>{statusMeta[selectedStep.status].label}</Badge>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">
                    <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
                      <span>作用</span>
                      <span
                        className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-slate-400/20 text-[10px] text-slate-500 dark:bg-white/10 dark:text-slate-400"
                        title={stepDescription(selectedStep)}
                        aria-label={`${selectedStep.label} 作用说明`}
                        tabIndex={0}
                      >
                        i
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">{stepDescription(selectedStep)}</p>
                  </div>
                  <div><div className="mb-2 text-xs font-semibold text-slate-500">输入</div><div className="text-xs leading-5 text-slate-600 dark:text-slate-300">{selectedStep.inputSummary || "-"}</div><div className="mt-2"><ProfileSummary profile={selectedStep.inputProfile} /></div></div>
                  <div><div className="mb-2 text-xs font-semibold text-slate-500">输出</div><div className="text-xs leading-5 text-slate-600 dark:text-slate-300">{selectedStep.outputSummary || selectedStep.skipReason || "等待执行"}</div><div className="mt-2"><ProfileSummary profile={selectedStep.outputProfile} /></div></div>
                  {selectedStep.generatedFeatures.length ? <div><div className="mb-2 text-xs font-semibold text-slate-500">生成 Features</div><div className="flex flex-wrap gap-1.5">{selectedStep.generatedFeatures.map((name) => <span key={name} className="rounded-md bg-cyan-50 px-2 py-1 text-[11px] text-cyan-700 dark:bg-cyan-400/10 dark:text-cyan-200">{name}</span>)}</div></div> : null}
                  {selectedStep.warnings.length ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">{selectedStep.warnings.join("；")}</div> : null}
                  {selectedStep.error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-100">{selectedStep.error}</div> : null}
                </div>
              </div>
            ) : <div className="text-sm text-slate-500">选择一个步骤查看详情。</div>}
          </div>
        ) : (
          <div className="grid gap-0 2xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="min-w-0 bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] bg-[size:24px_24px] p-4 sm:p-5">
              <div className="mx-auto max-w-5xl">
                {sourceStep ? <StepNode step={sourceStep} active={selectedStep?.id === sourceStep.id} onClick={() => setSelectedStepId(sourceStep.id)} /> : null}
                <FlowArrow active={sourceStep?.status === "completed" && generatorSteps.some((step) => step.status === "running")} />
                {generatorSteps.length ? (
                  <div>
                    <div className="mb-2 text-center text-[10px] font-semibold tracking-[0.18em] text-slate-400">特征机器</div>
                    <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-5">
                      {generatorSteps.map((step) => <StepNode key={step.id} step={step} active={selectedStep?.id === step.id} onClick={() => setSelectedStepId(step.id)} />)}
                    </div>
                  </div>
                ) : null}
                <FlowArrow active={generatorSteps.some((step) => step.status === "completed") && trunkSteps.some((step) => step.status === "running")} />
                <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-4">
                  {trunkSteps.map((step) => <StepNode key={step.id} step={step} active={selectedStep?.id === step.id} onClick={() => setSelectedStepId(step.id)} />)}
                </div>
                {hasRunningStep ? <div className="mt-4 h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10"><div className="h-full w-1/3 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400" /></div> : null}
              </div>
            </div>

            <aside className="border-t border-slate-200 p-4 dark:border-white/10 2xl:border-l 2xl:border-t-0">
              {selectedStep ? (
                <div className="space-y-4">
                  <StepAnimation step={selectedStep} />
                  <div className="flex items-start justify-between gap-3">
                    <div><div className="text-xs text-slate-400">步骤 {selectedStep.sequence}</div><div className="mt-1 font-semibold text-slate-950 dark:text-white">{selectedStep.label}</div></div>
                    <Badge tone={statusMeta[selectedStep.status].tone}>{statusMeta[selectedStep.status].label}</Badge>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">
                    <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
                      <span>作用</span>
                      <span
                        className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-slate-400/20 text-[10px] text-slate-500 dark:bg-white/10 dark:text-slate-400"
                        title={stepDescription(selectedStep)}
                        aria-label={`${selectedStep.label} 作用说明`}
                        tabIndex={0}
                      >
                        i
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">{stepDescription(selectedStep)}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-lg bg-slate-50 p-3 dark:bg-[#0b1020]"><div className="text-slate-400">耗时</div><div className="mt-1 font-semibold text-slate-900 dark:text-white">{formatDuration(selectedStep.elapsedSeconds)}</div></div>
                    <div className="rounded-lg bg-slate-50 p-3 dark:bg-[#0b1020]"><div className="text-slate-400">进度</div><div className="mt-1 font-semibold text-slate-900 dark:text-white">{selectedStep.progressPercent}%</div></div>
                  </div>
                  <div><div className="mb-2 text-xs font-semibold text-slate-500">输入</div><div className="text-xs leading-5 text-slate-600 dark:text-slate-300">{selectedStep.inputSummary || "-"}</div><div className="mt-2"><ProfileSummary profile={selectedStep.inputProfile} /></div></div>
                  <div><div className="mb-2 text-xs font-semibold text-slate-500">输出</div><div className="text-xs leading-5 text-slate-600 dark:text-slate-300">{selectedStep.outputSummary || selectedStep.skipReason || "等待执行"}</div><div className="mt-2"><ProfileSummary profile={selectedStep.outputProfile} /></div></div>
                  {selectedStep.generatedFeatures.length ? <div><div className="mb-2 text-xs font-semibold text-slate-500">生成 Features</div><div className="flex flex-wrap gap-1.5">{selectedStep.generatedFeatures.map((name) => <span key={name} className="rounded-md bg-cyan-50 px-2 py-1 text-[11px] text-cyan-700 dark:bg-cyan-400/10 dark:text-cyan-200">{name}</span>)}</div></div> : null}
                  {selectedStep.warnings.length ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">{selectedStep.warnings.join("；")}</div> : null}
                  {selectedStep.error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-100">{selectedStep.error}</div> : null}
                </div>
              ) : <div className="text-sm text-slate-500">选择一个步骤查看详情。</div>}
            </aside>
          </div>
        )
      ) : null}
    </div>
  );
}
