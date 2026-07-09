import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  cancelExperimentAgentRun,
  createExperimentAgentRun,
  fetchExperimentAgentHistory,
  fetchExperimentAgentRun
} from "../../shared/api/client";
import { ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, SideDrawer } from "../../shared/components/Ui";
import type {
  AgentArtifact,
  AgentHistoryItem,
  AgentRunDetail,
  AgentRunRequest,
  AgentSkillInvocation,
  AttributionSnapshot,
  ExperimentDetail
} from "../../shared/types/api";

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

function ChartArtifactPreview({ artifact }: { artifact: AgentArtifact }) {
  const payload = artifact.payload as {
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
  const payload = artifact.payload as Record<string, unknown>;
  const markdown = typeof payload.contentMarkdown === "string" ? payload.contentMarkdown : typeof payload.content === "string" ? payload.content : null;
  const bulletItems = Array.isArray(payload.bullets) ? payload.bullets.filter((item): item is string => typeof item === "string") : [];
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={artifact.kind === "chart" ? "info" : artifact.kind === "warning" ? "warn" : artifact.kind === "report" ? "good" : "neutral"}>
          {artifact.kind}
        </Badge>
        {artifact.sourceSkillId ? <Badge tone="neutral">{artifact.sourceSkillId}</Badge> : null}
        {artifact.linksToReport ? <Badge tone="good">可写入报告</Badge> : null}
      </div>
      <div className="mt-3 text-base font-semibold text-slate-950 dark:text-white">{artifact.title}</div>
      <div className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{artifact.summary}</div>

      {artifact.kind === "chart" ? <div className="mt-4"><ChartArtifactPreview artifact={artifact} /></div> : null}

      {markdown ? (
        <pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200">
          {markdown}
        </pre>
      ) : null}

      {bulletItems.length ? (
        <div className="mt-4 space-y-1 text-sm text-slate-700 dark:text-slate-200">
          {bulletItems.map((item) => <div key={item}>• {item}</div>)}
        </div>
      ) : null}
    </div>
  );
}

function InvocationCard({ invocation }: { invocation: AgentSkillInvocation }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-white/10 dark:bg-[#0b1020]">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-slate-900 dark:text-white">{invocation.skillId}</div>
        <Badge tone={stepTone(invocation.status)}>{invocation.status}</Badge>
      </div>
      <div className="mt-2 space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
        <div>输入：{invocation.inputSummary || "-"}</div>
        <div>输出：{invocation.outputSummary || "-"}</div>
        <div>开始：{formatDateTime(invocation.startedAt)}</div>
        <div>结束：{formatDateTime(invocation.finishedAt)}</div>
      </div>
      {invocation.warning ? <div className="mt-2 text-xs text-amber-700 dark:text-amber-200">{invocation.warning}</div> : null}
      {invocation.error ? <div className="mt-2 text-xs text-rose-700 dark:text-rose-200">{invocation.error}</div> : null}
    </div>
  );
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
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<AgentHistoryItem[]>(historySummary);
  const [run, setRun] = useState<AgentRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consumedLaunchNonce, setConsumedLaunchNonce] = useState("");
  const [selectedHistoryRunId, setSelectedHistoryRunId] = useState<string>("");
  const pollTimerRef = useRef<number | null>(null);

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
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (!open || !run || !["running", "planned"].includes(run.status)) return;
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
  }, [open, run]);

  async function handleSubmit(text = prompt, autoExecute = true) {
    const nextPrompt = text.trim();
    if (!nextPrompt) return;
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
        autoExecute
      };
      const response = await createExperimentAgentRun(experimentId, request);
      await refreshRun(response.runId);
      setPrompt(nextPrompt);
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
      await refreshRun(runId);
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
    setError(null);
  }

  const context = run?.context;
  const displayedSkills = run?.availableSkills.length ? run.availableSkills : availableSkills;
  const assistantSummary =
    run?.summary ??
    [...(run?.messages ?? [])].reverse().find((message) => message.role === "assistant")?.content ??
    null;
  const contextWarnings = context?.warnings?.length ? context.warnings : attribution?.warnings ?? [];

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title="归因 Agent"
      description="这个 Agent 只在当前实验上下文里工作：先给计划，再调用 skills，结果可回放、可中断。"
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
        </div>

        <ErrorBanner message={error} />

        <section className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-white">1. 对话区</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">支持自动规划、自动执行，也可以只重新规划不执行。</div>
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
              <textarea
                className={`${controls.input} min-h-[120px]`}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="例如：这次最主要的下降原因是什么？生成一张管理层可看的瀑布图并写入报告。"
                disabled={loading}
              />
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className={controls.primaryButton} disabled={loading || !prompt.trim()} onClick={() => void handleSubmit()}>
                  {loading ? "执行中..." : "交给 Agent"}
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
                <div>最近摘要：{assistantSummary ?? "等待 Agent 输出。"}</div>
              </div>
            </div>
          </div>

          {run?.messages.length ? (
            <div className="mt-4 space-y-3">
              {run.messages.slice(-6).map((message, index) => (
                <div
                  key={`${message.createdAt}:${index}`}
                  className={`rounded-2xl px-4 py-3 text-sm leading-6 ${
                    message.role === "assistant"
                      ? "border border-cyan-200 bg-cyan-50 text-cyan-900 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100"
                      : message.role === "system"
                        ? "border border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100"
                        : "border border-slate-200 bg-slate-50 text-slate-700 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-200"
                  }`}
                >
                  <div className="mb-1 text-[11px] uppercase tracking-[0.12em] opacity-75">{message.role} · {formatDateTime(message.createdAt)}</div>
                  <div className="whitespace-pre-wrap">{message.content}</div>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-white">2. Agent Plan</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">先规划、再执行。每一步会记录读了什么、跑了什么、生成了什么。</div>
            </div>
            <div className="flex flex-wrap gap-2">
              {displayedSkills.slice(0, 6).map((skill) => <Badge key={skill.skillId} tone="neutral">{skill.skillId}</Badge>)}
            </div>
          </div>

          {run?.risks.length ? (
            <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
              风险提示：{run.risks.join("；")}
            </div>
          ) : null}

          <div className="space-y-3">
            {run?.plan.length ? run.plan.map((step) => (
              <div key={step.stepId} className="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold text-slate-900 dark:text-white">{step.title}</div>
                    <div className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{step.detail}</div>
                  </div>
                  <Badge tone={stepTone(step.status)}>{step.status}</Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge tone="neutral">{step.skillId}</Badge>
                  {step.reads.map((item) => <Badge key={item} tone="neutral">{item}</Badge>)}
                  {step.runsModel ? <Badge tone="warn">会跑模型</Badge> : null}
                  {step.generatesChart ? <Badge tone="info">会生成图</Badge> : null}
                  {step.writesReport ? <Badge tone="good">会写报告</Badge> : null}
                  {step.estimatedDuration ? <Badge tone="info">{step.estimatedDuration}</Badge> : null}
                </div>
              </div>
            )) : <div className="text-sm text-slate-500 dark:text-slate-400">还没有执行计划。</div>}
          </div>

          {run?.skillInvocations.length ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {run.skillInvocations.map((invocation) => <InvocationCard key={invocation.invocationId} invocation={invocation} />)}
            </div>
          ) : null}
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-white">3. Artifacts</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">新生成的图、归因摘要、报告片段和实验建议都会出现在这里。</div>
            </div>
            {run ? <Badge tone="info">{run.artifacts.length} artifacts</Badge> : null}
          </div>
          <div className="space-y-3">
            {run?.artifacts.length ? run.artifacts.map((artifact) => <ArtifactCard key={artifact.artifactId} artifact={artifact} />) : (
              <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                这里会显示 Agent 本轮生成的新图、分析结果卡和报告片段。
              </div>
            )}
          </div>
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-white">4. Context & History</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">当前实验、模型、选中的对象，以及历史对话回放都在这里。</div>
            </div>
            {historyLoading ? <Badge tone="info">刷新中</Badge> : null}
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="space-y-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
              <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Context</div>
              <div className="space-y-2 text-sm text-slate-700 dark:text-slate-200">
                <div>实验：{experiment?.experimentName ?? context?.experimentName ?? experimentId}</div>
                <div>目标列：{context?.targetColumn ?? experiment?.targetColumn ?? "-"}</div>
                <div>推荐模型：{experiment?.recommendedModelId ?? context?.recommendedModelId ?? "-"}</div>
                <div>当前页面：{currentPage}</div>
                <div>当前 Tab：{context?.currentTab ?? currentTab ?? "-"}</div>
                <div>当前模型：{context?.selectedModelId ?? selectedModelId ?? "-"}</div>
                <div>当前特征：{context?.selectedFeatureId ?? selectedFeatureId ?? "-"}</div>
                <div>当前异常点：{context?.selectedAnomalyTime ?? selectedAnomalyTime ?? "-"}</div>
                <div>可用协变量：{context?.covariates.length ?? 0}</div>
              </div>
              {contextWarnings.length ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                  {contextWarnings.join("；")}
                </div>
              ) : null}
            </div>

            <div className="space-y-3">
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
          </div>
        </section>
      </div>
    </SideDrawer>
  );
}
