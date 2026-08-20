import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  cancelExperimentAgentRun,
  createExperimentAgentRun,
  fetchExperimentAgentHistory,
  fetchExperimentAgentRun,
  subscribeExperimentAgentRun
} from "../../shared/api/client";
import { loadDeepSeekSettings } from "../../shared/api/deepseekSettings";
import { ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, SideDrawer } from "../../shared/components/Ui";
import type {
  AgentArtifact,
  AgentConversationItem,
  AgentHistoryItem,
  AgentRunDetail,
  AgentRunRequest,
  AgentStreamEvent,
  AgentSkillInvocation,
  AttributionSnapshot,
  ExperimentDetail
} from "../../shared/types/api";

type LegacyAgentArtifact = AgentArtifact & {
  payload?: Record<string, unknown>;
  linksToReport?: boolean;
};

type LegacyAgentSkillInvocation = AgentSkillInvocation & {
  warning?: string | null;
};

type LegacyPlanStep = AgentRunDetail["plan"][number] & {
  detail?: string;
  runsModel?: boolean;
  generatesChart?: boolean;
  writesReport?: boolean;
  estimatedDuration?: string | null;
};

export interface AgentLaunchRequest {
  prompt: string;
  nonce: string;
  autoExecute?: boolean;
}

function statusTone(status: AgentRunDetail["status"] | AgentHistoryItem["status"]): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "completed") return "good";
  if (status === "running") return "info";
  if (status === "failed") return "bad";
  if (status === "cancelled") return "warn";
  return "neutral";
}

function stepTone(status: string): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "completed") return "good";
  if (status === "running") return "info";
  if (status === "failed") return "bad";
  if (status === "cancelled" || status === "skipped") return "warn";
  return "neutral";
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Math.abs(value) < 1 ? value.toFixed(4) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map((item) => formatValue(item)).join("、");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function normalizeArtifact(artifact: LegacyAgentArtifact) {
  const data = asRecord(artifact.data);
  const payload = Object.keys(data).length ? data : asRecord(artifact.payload);
  const markdown =
    typeof artifact.markdown === "string"
      ? artifact.markdown
      : typeof payload.contentMarkdown === "string"
        ? payload.contentMarkdown
        : typeof payload.content === "string"
          ? payload.content
          : null;
  return {
    artifactId: artifact.artifactId,
    kind: artifact.kind ?? "summary",
    title: artifact.title ?? "未命名 Artifact",
    summary: artifact.summary ?? "",
    sourceSkillId: artifact.sourceSkillId ?? "",
    createdAt: artifact.createdAt ?? null,
    reportCompatible: Boolean(artifact.reportCompatible ?? artifact.linksToReport),
    downloadable: Boolean(artifact.downloadable),
    markdown,
    bulletItems: asStringArray(payload.bullets),
    data: payload
  };
}

function normalizeInvocation(invocation: LegacyAgentSkillInvocation) {
  const warnings = Array.isArray(invocation.warnings)
    ? invocation.warnings.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : invocation.warning
      ? [invocation.warning]
      : [];
  return {
    ...invocation,
    inputSummary: invocation.inputSummary ?? "-",
    outputSummary: invocation.outputSummary ?? "-",
    warnings,
    artifactIds: Array.isArray(invocation.artifactIds) ? invocation.artifactIds : [],
  };
}

function normalizePlanStep(step: LegacyPlanStep) {
  const runs = Array.isArray(step.runs) ? [...step.runs] : [];
  const generates = Array.isArray(step.generates) ? [...step.generates] : [];
  if (step.runsModel) runs.push("model-run");
  if (step.generatesChart) generates.push("chart");
  if (step.writesReport) generates.push("report");
  return {
    ...step,
    description: step.description || step.detail || "当前步骤暂无详细说明。",
    reads: Array.isArray(step.reads) ? step.reads : [],
    runs: Array.from(new Set(runs.filter(Boolean))),
    generates: Array.from(new Set(generates.filter(Boolean))),
    sideEffects: Array.isArray(step.sideEffects) ? step.sideEffects : [],
    warnings: Array.isArray(step.warnings) ? step.warnings : [],
  };
}

function ChartArtifactPreview({ artifact }: { artifact: AgentArtifact }) {
  const normalized = normalizeArtifact(artifact as LegacyAgentArtifact);
  const payload = normalized.data as {
    chartType?: string;
    summary?: string[];
    contributions?: Array<{ label: string; value: number }>;
    cells?: Array<{ row: string; column: string; value: number }>;
    points?: Array<Record<string, unknown>>;
    series?: Array<Record<string, unknown>>;
  };
  const chartType = payload.chartType ?? "chart";

  if (chartType === "waterfall" && Array.isArray(payload.contributions)) {
    const maxValue = Math.max(...payload.contributions.map((item) => Math.abs(item.value)), 1);
    return (
      <div className="space-y-3">
        {payload.contributions.map((item) => (
          <div key={item.label} className="space-y-1">
            <div className="flex items-center justify-between gap-3 text-sm text-slate-700 dark:text-slate-200">
              <span>{item.label}</span>
              <span>{formatValue(item.value)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
              <div
                className={`h-full rounded-full ${item.value >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
                style={{ width: `${Math.max(6, (Math.abs(item.value) / maxValue) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (chartType === "heatmap" && Array.isArray(payload.cells)) {
    const values = payload.cells.map((item) => Number(item.value || 0));
    const minValue = Math.min(...values, 0);
    const maxValue = Math.max(...values, 1);
    return (
      <div className="grid gap-2 sm:grid-cols-2">
        {payload.cells.slice(0, 16).map((cell, index) => {
          const ratio = maxValue === minValue ? 0.5 : (Number(cell.value || 0) - minValue) / (maxValue - minValue);
          const color = `rgba(34,211,238,${0.15 + ratio * 0.65})`;
          return (
            <div key={`${cell.row}:${cell.column}:${index}`} className="rounded-2xl border border-slate-200 px-3 py-3 dark:border-white/10" style={{ background: color }}>
              <div className="text-[11px] uppercase tracking-[0.12em] text-slate-600 dark:text-slate-100">{cell.row}</div>
              <div className="mt-1 text-sm text-slate-700 dark:text-slate-100">{cell.column}</div>
              <div className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">{formatValue(cell.value)}</div>
            </div>
          );
        })}
      </div>
    );
  }

  if (chartType === "bubble" && Array.isArray(payload.points)) {
    return (
      <div className="overflow-auto rounded-2xl border border-slate-200 dark:border-white/10">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-600 dark:bg-[#0b1020] dark:text-slate-300">
            <tr>
              <th className="px-3 py-2">label</th>
              <th className="px-3 py-2">x</th>
              <th className="px-3 py-2">y</th>
              <th className="px-3 py-2">size</th>
            </tr>
          </thead>
          <tbody>
            {payload.points.slice(0, 10).map((point, index) => (
              <tr key={index} className="border-t border-slate-200 dark:border-white/10">
                <td className="px-3 py-2">{formatValue(point.label)}</td>
                <td className="px-3 py-2">{formatValue(point.x)}</td>
                <td className="px-3 py-2">{formatValue(point.y)}</td>
                <td className="px-3 py-2">{formatValue(point.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm dark:border-white/10 dark:bg-[#0b1020]">
      <div className="font-medium text-slate-800 dark:text-slate-100">预览类型：{chartType}</div>
      {(payload.summary ?? []).length ? (
        <div className="space-y-1 text-slate-600 dark:text-slate-300">
          {(payload.summary ?? []).map((item) => <div key={item}>• {item}</div>)}
        </div>
      ) : (
        <pre className="overflow-auto whitespace-pre-wrap text-xs text-slate-600 dark:text-slate-300">{JSON.stringify(payload, null, 2)}</pre>
      )}
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: AgentArtifact }) {
  const normalized = normalizeArtifact(artifact as LegacyAgentArtifact);
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={normalized.kind === "chart" ? "info" : normalized.kind === "warning" ? "warn" : normalized.kind === "report" ? "good" : "neutral"}>
          {normalized.kind}
        </Badge>
        {normalized.sourceSkillId ? <Badge tone="neutral">{normalized.sourceSkillId}</Badge> : null}
        {normalized.reportCompatible ? <Badge tone="good">可写入报告</Badge> : null}
        {normalized.downloadable ? <Badge tone="info">可下载</Badge> : null}
      </div>
      <div className="mt-3 text-base font-semibold text-slate-950 dark:text-white">{normalized.title}</div>
      <div className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{normalized.summary}</div>

      {normalized.kind === "chart" ? <div className="mt-4"><ChartArtifactPreview artifact={artifact} /></div> : null}

      {normalized.markdown ? (
        <pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200">
          {normalized.markdown}
        </pre>
      ) : null}

      {normalized.bulletItems.length ? (
        <div className="mt-4 space-y-1 text-sm text-slate-700 dark:text-slate-200">
          {normalized.bulletItems.map((item) => <div key={item}>• {item}</div>)}
        </div>
      ) : null}

      {!normalized.markdown && !normalized.bulletItems.length && normalized.kind !== "chart" && Object.keys(normalized.data).length ? (
        <pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200">
          {JSON.stringify(normalized.data, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

function InvocationCard({ invocation }: { invocation: AgentSkillInvocation }) {
  const normalized = normalizeInvocation(invocation as LegacyAgentSkillInvocation);
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-white/10 dark:bg-[#0b1020]">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-slate-900 dark:text-white">{normalized.skillId}</div>
        <Badge tone={stepTone(normalized.status)}>{normalized.status}</Badge>
      </div>
      <div className="mt-2 space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
        <div>输入：{normalized.inputSummary}</div>
        <div>输出：{normalized.outputSummary}</div>
        <div>开始：{formatDateTime(normalized.startedAt)}</div>
        <div>结束：{formatDateTime(normalized.finishedAt)}</div>
      </div>
      {normalized.warnings.length ? <div className="mt-2 text-xs text-amber-700 dark:text-amber-200">{normalized.warnings.join("；")}</div> : null}
      {normalized.error ? <div className="mt-2 text-xs text-rose-700 dark:text-rose-200">{normalized.error}</div> : null}
    </div>
  );
}

function sortConversation(items: AgentConversationItem[]) {
  return [...items].sort((left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime());
}

function mergeConversationItem(items: AgentConversationItem[], incoming: AgentConversationItem, delta?: string) {
  let updated = false;
  const next = items.map((item) => {
    if (item.itemId !== incoming.itemId) return item;
    updated = true;
    return {
      ...item,
      ...incoming,
      contentMarkdown: delta ? `${item.contentMarkdown}${delta}` : incoming.contentMarkdown,
      streamState: delta ? "streaming" : incoming.streamState
    };
  });
  if (!updated) {
    next.push({
      ...incoming,
      contentMarkdown: delta ? delta : incoming.contentMarkdown,
      streamState: delta ? "streaming" : incoming.streamState
    });
  }
  return sortConversation(next);
}

function mergePlanStep(plan: AgentRunDetail["plan"], incoming: AgentRunDetail["plan"][number]) {
  let updated = false;
  const next = plan.map((step) => {
    if (step.stepId !== incoming.stepId) return step;
    updated = true;
    return { ...step, ...incoming };
  });
  if (!updated) next.push(incoming);
  return next;
}

function mergeArtifact(artifacts: AgentArtifact[], incoming: AgentArtifact) {
  if (artifacts.some((artifact) => artifact.artifactId === incoming.artifactId)) return artifacts;
  return [...artifacts, incoming].sort((left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime());
}

function applyStreamEvent(run: AgentRunDetail | null, event: AgentStreamEvent): AgentRunDetail | null {
  if (!run || run.runId !== event.runId) return run;
  let next = { ...run };
  if (event.status && (event.eventType === "status" || event.eventType === "error")) {
    next.status = event.status as AgentRunDetail["status"];
  }
  if (event.planStep) next.plan = mergePlanStep(run.plan, event.planStep);
  if (event.artifact) next.artifacts = mergeArtifact(run.artifacts, event.artifact);
  if (event.conversationItem) {
    next.conversation = mergeConversationItem(run.conversation, event.conversationItem, event.eventType === "message_delta" ? event.delta ?? "" : undefined);
  }
  if (event.eventType === "message_final" && event.conversationItem?.kind === "assistant") {
    next.summary = event.conversationItem.contentMarkdown;
  }
  return next;
}

function conversationTone(item: AgentConversationItem): string {
  switch (item.kind) {
    case "user":
      return "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200";
    case "assistant":
      return "border-cyan-200 bg-cyan-50 text-cyan-900 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100";
    case "plan":
      return "border-violet-200 bg-violet-50 text-violet-900 dark:border-violet-400/20 dark:bg-violet-400/10 dark:text-violet-100";
    case "action":
      return "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100";
    case "artifact":
      return "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-100";
    default:
      return "border-slate-200 bg-white text-slate-700 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-200";
  }
}

function kindLabel(item: AgentConversationItem): string {
  switch (item.kind) {
    case "user":
      return "用户";
    case "assistant":
      return "Agent";
    case "plan":
      return "计划";
    case "action":
      return "行动";
    case "artifact":
      return "Artifact";
    default:
      return "状态";
  }
}

export function AttributionAgentDrawer({
  open,
  onClose,
  experimentId,
  experiment,
  currentPage,
  currentTab,
  selectedModelId = null,
  selectedFeatureId = null,
  selectedArtifactId = null,
  selectedVisualId = null,
  selectedAnomalyTime = null,
  historySummary = [],
  availableSkills = [],
  attribution = null,
  launchRequest = null
}: {
  open: boolean;
  onClose: () => void;
  experimentId: string;
  experiment?: ExperimentDetail | null;
  currentPage: string;
  currentTab?: string | null;
  selectedModelId?: string | null;
  selectedFeatureId?: string | null;
  selectedArtifactId?: string | null;
  selectedVisualId?: string | null;
  selectedAnomalyTime?: string | null;
  historySummary?: AgentHistoryItem[];
  availableSkills?: ExperimentDetail["availableAgentSkills"];
  attribution?: AttributionSnapshot | null;
  launchRequest?: AgentLaunchRequest | null;
}) {
  const [activeTab, setActiveTab] = useState<"conversation" | "artifacts" | "history" | "context">("conversation");
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<AgentHistoryItem[]>(historySummary);
  const [run, setRun] = useState<AgentRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamFallback, setStreamFallback] = useState(false);
  const [consumedLaunchNonce, setConsumedLaunchNonce] = useState("");
  const [selectedHistoryRunId, setSelectedHistoryRunId] = useState<string>("");
  const [selectedArtifactFocus, setSelectedArtifactFocus] = useState<string>("");
  const pollTimerRef = useRef<number | null>(null);
  const streamStopRef = useRef<(() => void) | null>(null);
  const lastStreamCursorRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    setHistory(historySummary);
  }, [historySummary, open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setHistoryLoading(true);
    void fetchExperimentAgentHistory(experimentId)
      .then((items) => {
        if (cancelled) return;
        setHistory(items);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Agent 历史加载失败。");
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [experimentId, open]);

  async function refreshRun(runId: string) {
    const detail = await fetchExperimentAgentRun(experimentId, runId);
    setRun(detail);
    setSelectedHistoryRunId(runId);
    return detail;
  }

  useEffect(() => {
    if (!open || !launchRequest || launchRequest.nonce === consumedLaunchNonce) return;
    setConsumedLaunchNonce(launchRequest.nonce);
    setPrompt(launchRequest.prompt);
    void handleSubmit(launchRequest.prompt, launchRequest.autoExecute ?? true);
  }, [consumedLaunchNonce, launchRequest, open]);

  useEffect(() => {
    streamStopRef.current?.();
    streamStopRef.current = null;
    if (!open || !run || !["running", "planned"].includes(run.status)) return;
    setStreamFallback(false);
    streamStopRef.current = subscribeExperimentAgentRun(
      experimentId,
      run.runId,
      (event) => {
        lastStreamCursorRef.current = Math.max(lastStreamCursorRef.current, event.cursor);
        setRun((current) => applyStreamEvent(current, event));
      },
      {
        afterCursor: lastStreamCursorRef.current,
        onError: () => setStreamFallback(true),
      }
    );
    return () => {
      streamStopRef.current?.();
      streamStopRef.current = null;
    };
  }, [experimentId, open, run?.runId, run?.status]);

  useEffect(() => {
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (!open || !run || !["running", "planned"].includes(run.status) || !streamFallback) return;
    pollTimerRef.current = window.setInterval(() => {
      void refreshRun(run.runId).catch(() => {
        // keep last visible state
      });
    }, 1500);
    return () => {
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [open, run?.runId, run?.status, streamFallback]);

  async function handleSubmit(text = prompt, autoExecute = true) {
    const nextPrompt = text.trim();
    if (!nextPrompt) return;
    const settings = loadDeepSeekSettings();
    if (!settings.apiKey.trim() || !settings.baseUrl.trim() || !settings.model.trim()) {
      setError("请先在 API 设置中配置 DeepSeek 后再使用归因 Agent。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const request: AgentRunRequest = {
        prompt: nextPrompt,
        currentPage,
        currentTab,
        selectedModelId,
        selectedFeatureId,
        selectedArtifactId,
        selectedVisualId,
        selectedAnomalyTime,
        autoExecute,
        llm: {
          provider: "deepseek",
          apiKey: settings.apiKey,
          baseUrl: settings.baseUrl,
          model: settings.model,
          stream: true
        }
      };
      const response = await createExperimentAgentRun(experimentId, request);
      lastStreamCursorRef.current = 0;
      setStreamFallback(false);
      await refreshRun(response.runId);
      setPrompt(nextPrompt);
      setActiveTab("conversation");
      setHistory(await fetchExperimentAgentHistory(experimentId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent 请求失败。");
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel() {
    if (!run?.canCancel) return;
    setLoading(true);
    setError(null);
    try {
      await cancelExperimentAgentRun(experimentId, run.runId);
      await refreshRun(run.runId);
      setHistory(await fetchExperimentAgentHistory(experimentId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止 Agent 失败。");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectHistory(runId: string) {
    setLoading(true);
    setError(null);
    try {
      lastStreamCursorRef.current = 0;
      await refreshRun(runId);
      setActiveTab("conversation");
    } catch (err) {
      setError(err instanceof Error ? err.message : "历史回放加载失败。");
    } finally {
      setLoading(false);
    }
  }

  function handleClear() {
    setPrompt("");
    setRun(null);
    setSelectedHistoryRunId("");
    setSelectedArtifactFocus("");
    setError(null);
    lastStreamCursorRef.current = 0;
  }

  const context = run?.context;
  const displayedSkills = run?.availableSkills.length ? run.availableSkills : availableSkills;
  const assistantConversation = run?.conversation.filter((item) => item.kind === "assistant") ?? [];
  const assistantSummary = run?.summary ?? (assistantConversation.length ? assistantConversation[assistantConversation.length - 1]?.contentMarkdown : null) ?? null;
  const contextWarnings = context?.warnings?.length ? context.warnings : attribution?.warnings ?? [];
  const normalizedPlan = useMemo(() => (run?.plan ?? []).map((step) => normalizePlanStep(step as LegacyPlanStep)), [run?.plan]);
  const normalizedArtifacts = useMemo(() => (run?.artifacts ?? []).map((artifact) => normalizeArtifact(artifact as LegacyAgentArtifact)), [run?.artifacts]);
  const activeArtifact = normalizedArtifacts.find((artifact) => artifact.artifactId === selectedArtifactFocus) ?? (normalizedArtifacts.length ? normalizedArtifacts[normalizedArtifacts.length - 1] : null);
  const transcript = sortConversation((run?.conversation ?? []).filter((item) => item.kind === "user" || item.kind === "assistant"));
  const showPendingTranscript = loading && transcript.length === 0 && prompt.trim().length > 0;
  const runningStep = normalizedPlan.find((step) => step.status === "running") ?? null;
  const completedStepCount = normalizedPlan.filter((step) => step.status === "completed").length;
  const targetAwarePrompt = `影响${context?.targetColumn ?? experiment?.targetColumn ?? "目标"}列的主要原因是什么？`;
  const deepSeekConfigured = (() => {
    const settings = loadDeepSeekSettings();
    return Boolean(settings.apiKey.trim() && settings.baseUrl.trim() && settings.model.trim());
  })();

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title="归因 Agent"
      description="基于当前实验的真实证据连续分析，并把每一步新增的发现、解释和下一步实时展示出来。"
      widthClassName="w-full max-w-[980px]"
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <Link className={controls.secondaryButton} to={`/experiments/${experimentId}`}>
            实验详情
          </Link>
          <Link className={controls.secondaryButton} to={`/experiments/${experimentId}/attribution`}>
            Attribution Lab
          </Link>
          {run ? <Badge tone={statusTone(run.status)}>{run.status}</Badge> : null}
          {run?.estimatedDuration ? <Badge tone="info">预计 {run.estimatedDuration}</Badge> : null}
          {run?.canCancel ? <Badge tone="warn">可中断</Badge> : null}
          {run?.llmSession ? <Badge tone="good">{run.llmSession.model}</Badge> : null}
          {streamFallback ? <Badge tone="warn">SSE 已断开，已退回轮询</Badge> : null}
        </div>

        <ErrorBanner message={error} />

        <section className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-white">提问与执行</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">你提问后，我会顺着证据往前走，并把每一步的发现、解释和下一步实时写出来。</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={controls.secondaryButton} onClick={() => void handleSubmit(prompt, false)} disabled={loading || !prompt.trim()}>
                重新规划
              </button>
              <button type="button" className={controls.secondaryButton} onClick={handleClear}>
                清空
              </button>
              <button type="button" className={controls.secondaryButton} onClick={() => void handleCancel()} disabled={!run?.canCancel || loading}>
                停止当前任务
              </button>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
            <div className="space-y-3">
              {!deepSeekConfigured ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                  请先在 API 设置中配置 DeepSeek 后再使用归因 Agent。
                </div>
              ) : null}
              <textarea
                className={`${controls.input} min-h-[120px]`}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={`例如：${targetAwarePrompt}`}
                disabled={loading}
              />
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className={controls.primaryButton} disabled={loading || !prompt.trim()} onClick={() => void handleSubmit()}>
                  {loading ? "执行中..." : "交给 Agent"}
                </button>
                <button type="button" className={controls.secondaryButton} disabled={loading} onClick={() => setPrompt(targetAwarePrompt)}>
                  使用主因问题
                </button>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  当前上下文：{currentPage}{currentTab ? ` / ${currentTab}` : ""}
                </span>
              </div>
            </div>

            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
              <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">当前执行状态</div>
              <div className="mt-3 space-y-3 text-sm text-slate-700 dark:text-slate-200">
                <div>实验：{experiment?.experimentName ?? context?.experimentName ?? experimentId}</div>
                <div>目标列：{context?.targetColumn ?? experiment?.targetColumn ?? "-"}</div>
                <div>当前模型：{context?.selectedModelId ?? selectedModelId ?? experiment?.recommendedModelId ?? "-"}</div>
                <div>当前步骤：{runningStep?.title ?? (run?.status === "completed" ? "已完成" : loading ? "正在接入本轮运行" : "等待开始")}</div>
                <div>计划进度：{normalizedPlan.length ? `${completedStepCount}/${normalizedPlan.length}` : "-"}</div>
                <div>最近摘要：{assistantSummary ?? (loading ? "正在连接第一批证据..." : "等待 Agent 输出。")}</div>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {[
              { id: "conversation", label: "对话" },
              { id: "artifacts", label: `Artifacts${run ? ` · ${run.artifacts.length}` : ""}` },
              { id: "history", label: `History${history.length ? ` · ${history.length}` : ""}` },
              { id: "context", label: "Context" }
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id as "conversation" | "artifacts" | "history" | "context")}
                className={`rounded-full px-4 py-2 text-sm transition ${
                  activeTab === tab.id
                    ? "bg-cyan-500 text-white"
                    : "border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700 dark:border-white/10 dark:text-slate-300 dark:hover:border-cyan-400/30 dark:hover:text-cyan-200"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === "conversation" ? (
            <div className="space-y-4">
              {run?.risks.length ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                  风险提示：{run.risks.join("；")}
                </div>
              ) : null}

              {transcript.length ? transcript.map((item) => {
                const relatedArtifact = normalizedArtifacts.find((artifact) => artifact.artifactId === item.artifactId) ?? null;
                const relatedStep = normalizedPlan.find((step) => step.stepId === item.stepId) ?? null;
                const isAssistant = item.kind === "assistant";
                return (
                  <div key={item.itemId} className={`analysis-card-rise rounded-3xl border px-4 py-4 ${conversationTone(item)}`}>
                    {isAssistant ? (
                      <div className="flex items-center justify-end gap-2 text-[11px] tracking-[0.08em] opacity-70">
                        <span>{formatDateTime(item.createdAt)}</span>
                        {item.streamState === "streaming" ? (
                          <span className="inline-flex items-center gap-1 text-cyan-600 dark:text-cyan-200">
                            <span className="analysis-live-dot h-2 w-2 rounded-full bg-current" />
                          </span>
                        ) : null}
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.12em] opacity-80">
                        <span>{kindLabel(item)}</span>
                        {item.title ? <span>· {item.title}</span> : null}
                        <span>· {formatDateTime(item.createdAt)}</span>
                        {item.status ? <Badge tone={stepTone(item.status)}>{item.status}</Badge> : null}
                      </div>
                    )}
                    <div className="mt-3 whitespace-pre-wrap text-sm leading-7">
                      {item.contentMarkdown || "..."}
                      {item.streamState === "streaming" && isAssistant ? (
                        <span className="ml-1 inline-block h-4 w-1 animate-pulse rounded bg-current align-middle opacity-70" />
                      ) : null}
                    </div>
                    {!isAssistant && relatedStep ? (
                      <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Badge tone="neutral">{relatedStep.skillId}</Badge>
                        {relatedStep.generates.map((value) => <Badge key={`${relatedStep.stepId}:${value}`} tone="info">生成 {value}</Badge>)}
                      </div>
                    ) : null}
                    {!isAssistant && relatedArtifact ? (
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedArtifactFocus(relatedArtifact.artifactId);
                          setActiveTab("artifacts");
                        }}
                        className="mt-3 rounded-2xl border border-current/20 px-3 py-2 text-left text-xs leading-5 transition hover:bg-white/40 dark:hover:bg-white/5"
                      >
                        查看 Artifact：{relatedArtifact.title}
                      </button>
                    ) : null}
                  </div>
                );
              }) : showPendingTranscript ? (
                <>
                  <div className="analysis-card-rise rounded-3xl border border-slate-200 bg-slate-50 px-4 py-4 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200">
                    <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.12em] opacity-80">
                      <span>用户</span>
                      <span>· 用户问题</span>
                      <span>· 刚刚</span>
                    </div>
                    <div className="mt-3 whitespace-pre-wrap text-sm leading-7">{prompt.trim()}</div>
                  </div>
                  <div className="analysis-card-rise rounded-3xl border border-cyan-200 bg-cyan-50 px-4 py-4 text-cyan-900 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100">
                    <div className="flex items-center justify-end gap-2 text-[11px] tracking-[0.08em] opacity-70">
                      <span>正在接入本轮运行</span>
                      <span className="inline-flex items-center gap-1 text-cyan-600 dark:text-cyan-200">
                        <span className="analysis-live-dot h-2 w-2 rounded-full bg-current" />
                      </span>
                    </div>
                    <div className="mt-3 whitespace-pre-wrap text-sm leading-7">
                      {"发现\n- 正在读取当前实验的第一批证据。\n\n解释\n- 我会先把已经跑出来的结果接上，再继续往下分析。\n\n下一步\n- 连上本轮 run 后，先读取第一步证据。"}
                      <span className="ml-1 inline-block h-4 w-1 animate-pulse rounded bg-current align-middle opacity-70" />
                    </div>
                  </div>
                </>
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                  这里会按时间顺序展示用户问题，以及 Agent 连续输出的发现、解释和下一步。
                </div>
              )}

              {run?.skillInvocations.length ? (
                <div className="grid gap-3 lg:grid-cols-2">
                  {run.skillInvocations.map((invocation) => <InvocationCard key={invocation.invocationId} invocation={invocation} />)}
                </div>
              ) : null}
            </div>
          ) : null}

          {activeTab === "artifacts" ? (
            <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
              <div className="space-y-3">
                {normalizedArtifacts.length ? normalizedArtifacts.map((artifact) => (
                  <button
                    key={artifact.artifactId}
                    type="button"
                    onClick={() => setSelectedArtifactFocus(artifact.artifactId)}
                    className={`w-full rounded-3xl border p-4 text-left transition ${
                      activeArtifact?.artifactId === artifact.artifactId
                        ? "border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10"
                        : "border-slate-200 bg-white hover:border-slate-300 dark:border-white/10 dark:bg-[#0b1020]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-900 dark:text-white">{artifact.title}</div>
                      <Badge tone={artifact.kind === "chart" ? "info" : artifact.kind === "report" ? "good" : "neutral"}>{artifact.kind}</Badge>
                    </div>
                    <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{artifact.summary}</div>
                  </button>
                )) : (
                  <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    当前还没有生成 artifact。
                  </div>
                )}
              </div>
              <div>
                {activeArtifact ? <ArtifactCard artifact={run?.artifacts.find((artifact) => artifact.artifactId === activeArtifact.artifactId) ?? run!.artifacts[0]} /> : (
                  <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    选择一条 artifact 查看详细内容。
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {activeTab === "history" ? (
            <div className="space-y-3">
              {historyLoading ? <Badge tone="info">刷新中</Badge> : null}
              {history.length ? history.map((item) => (
                <button
                  key={item.runId}
                  type="button"
                  onClick={() => void handleSelectHistory(item.runId)}
                  className={`w-full rounded-3xl border p-4 text-left transition ${
                    selectedHistoryRunId === item.runId
                      ? "border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10"
                      : "border-slate-200 bg-white hover:border-slate-300 dark:border-white/10 dark:bg-[#0b1020]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium text-slate-900 dark:text-white">{item.requestPreview}</div>
                    <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                  </div>
                  <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    <div>创建：{formatDateTime(item.createdAt)}</div>
                    <div>技能：{item.skillIds.join("、") || "-"}</div>
                    <div>Artifacts：{item.artifactCount}</div>
                    {item.lastAssistantMessage ? <div>最近回复：{item.lastAssistantMessage}</div> : null}
                  </div>
                </button>
              )) : (
                <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                  当前还没有 Agent 历史。
                </div>
              )}
            </div>
          ) : null}

          {activeTab === "context" ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
              <div className="space-y-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">实验上下文</div>
                <div className="space-y-2 text-sm text-slate-700 dark:text-slate-200">
                  <div>实验：{experiment?.experimentName ?? context?.experimentName ?? experimentId}</div>
                  <div>目标列：{context?.targetColumn ?? experiment?.targetColumn ?? "-"}</div>
                  <div>推荐模型：{experiment?.recommendedModelId ?? context?.recommendedModelId ?? "-"}</div>
                  <div>当前页面：{currentPage}</div>
                  <div>当前 Tab：{context?.currentTab ?? currentTab ?? "-"}</div>
                  <div>当前模型：{context?.selectedModelId ?? selectedModelId ?? "-"}</div>
                  <div>可用协变量：{context?.covariates.length ?? 0}</div>
                  <div>LLM：{run?.llmSession ? `${run.llmSession.provider} / ${run.llmSession.model}` : "未开始"}</div>
                </div>
                {contextWarnings.length ? (
                  <div className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                    {contextWarnings.join("；")}
                  </div>
                ) : null}
              </div>

              <div className="space-y-3">
                <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0b1020]">
                  <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">当前计划</div>
                  <div className="mt-3 space-y-3">
                    {normalizedPlan.length ? normalizedPlan.map((step) => (
                      <div key={step.stepId} className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-white/10 dark:bg-[#151b2e]">
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium text-slate-900 dark:text-white">{step.title}</div>
                          <Badge tone={stepTone(step.status)}>{step.status}</Badge>
                        </div>
                        <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{step.description}</div>
                      </div>
                    )) : <div className="text-sm text-slate-500 dark:text-slate-400">还没有执行计划。</div>}
                  </div>
                </div>

                <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0b1020]">
                  <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">可用 Skills</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {displayedSkills.slice(0, 10).map((skill) => <Badge key={skill.skillId} tone="neutral">{skill.skillId}</Badge>)}
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </SideDrawer>
  );
}
