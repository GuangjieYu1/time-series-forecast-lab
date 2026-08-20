import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useLabStore } from "../../app/store";
import {
  cancelAnalysisRun,
  fetchAnalysisProfile,
  fetchAnalysisRun,
  fetchAnalysisRunEvents,
  startClusteringWorkflow,
  startSupervisedWorkflow,
} from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import type { AnalysisRunEvent, DatasetProfile, WorkflowRunDetail, WorkflowStageDetail } from "../../shared/types/api";

type WorkflowPageType = "supervised_ml" | "clustering";

type WorkflowLocationState = {
  targetColumn?: string | null;
  featureColumns?: string[];
  clusterCount?: number | null;
  openedByAgent?: boolean;
};

function resolveWorkflowType(pathType: string | undefined): WorkflowPageType | null {
  if (pathType === "supervised-ml") return "supervised_ml";
  if (pathType === "clustering") return "clustering";
  return null;
}

function workflowLabel(type: WorkflowPageType) {
  return type === "supervised_ml" ? "监督学习 Workflow" : "聚类分析 Workflow";
}

function stageTone(stage: WorkflowStageDetail["status"]): "good" | "info" | "warn" | "bad" | "neutral" {
  if (stage === "completed") return "good";
  if (stage === "running") return "info";
  if (stage === "failed") return "bad";
  return "neutral";
}

function detailTone(status: WorkflowRunDetail["status"]): "good" | "info" | "warn" | "bad" | "neutral" {
  if (status === "completed") return "good";
  if (status === "running") return "info";
  if (status === "failed") return "bad";
  return "warn";
}

function defaultFeaturesForWorkflow(profile: DatasetProfile, workflowType: WorkflowPageType, targetColumn: string | null) {
  if (workflowType === "clustering") {
    return profile.columns
      .filter((column) => column.inferredType === "number" && !column.isConstant && !column.isPotentialIdentifier)
      .map((column) => column.name)
      .slice(0, 8);
  }
  return profile.columns
    .filter((column) => column.name !== targetColumn && !column.isConstant && !column.isPotentialIdentifier && ["number", "string", "boolean"].includes(column.inferredType))
    .map((column) => column.name)
    .slice(0, 12);
}

function formatMetricValue(value: unknown) {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (Array.isArray(value)) return `${value.length} items`;
  if (value && typeof value === "object") return "structured";
  return String(value ?? "-");
}

function upsertRun(history: WorkflowRunDetail[], nextRun: WorkflowRunDetail) {
  const existing = history.findIndex((item) => item.runId === nextRun.runId);
  if (existing === -1) return [nextRun, ...history];
  return history.map((item) => (item.runId === nextRun.runId ? nextRun : item));
}

export function AnalysisWorkflowPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { workflowType: rawWorkflowType } = useParams();
  const workflowType = resolveWorkflowType(rawWorkflowType);
  const locationState = (location.state ?? {}) as WorkflowLocationState;
  const { upload, selectedSheet } = useLabStore();

  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [experimentName, setExperimentName] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);
  const [clusterCount, setClusterCount] = useState(3);
  const [runDetail, setRunDetail] = useState<WorkflowRunDetail | null>(null);
  const [runEvents, setRunEvents] = useState<AnalysisRunEvent[]>([]);
  const [runHistory, setRunHistory] = useState<WorkflowRunDetail[]>([]);
  const [running, setRunning] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const seededForDataset = useRef<string>("");

  useEffect(() => {
    if (!upload || !selectedSheet || !workflowType) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAnalysisProfile({ uploadId: upload.uploadId, sheetName: selectedSheet.sheetName })
      .then((nextProfile) => {
        if (cancelled) return;
        setProfile(nextProfile);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "无法加载 workflow 所需的数据画像。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [upload?.uploadId, selectedSheet?.sheetName, workflowType]);

  useEffect(() => {
    if (!profile || !workflowType || !upload || !selectedSheet) return;
    const datasetKey = `${workflowType}:${upload.uploadId}:${selectedSheet.sheetName}`;
    if (seededForDataset.current === datasetKey) return;
    seededForDataset.current = datasetKey;
    const nextTarget = locationState.targetColumn ?? profile.targetCandidates[0] ?? "";
    const nextFeatures = locationState.featureColumns?.length
      ? locationState.featureColumns
      : defaultFeaturesForWorkflow(profile, workflowType, nextTarget || null);
    setExperimentName(
      workflowType === "supervised_ml"
        ? `${nextTarget || profile.targetCandidates[0] || "Target"} Supervised ML`
        : `${upload.fileName} Clustering`
    );
    setTargetColumn(nextTarget);
    setSelectedFeatures(nextFeatures);
    setClusterCount(locationState.clusterCount ?? 3);
  }, [locationState.clusterCount, locationState.featureColumns, locationState.targetColumn, profile, selectedSheet, upload, workflowType]);

  useEffect(() => {
    if (!runDetail?.runId || (runDetail.status !== "running" && runDetail.status !== "planned")) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const [detail, events] = await Promise.all([
          fetchAnalysisRun(runDetail.runId),
          fetchAnalysisRunEvents(runDetail.runId),
        ]);
        if (cancelled) return;
        setRunDetail(detail);
        setRunEvents(events.events);
        setRunHistory((current) => upsertRun(current, detail));
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "刷新 workflow 运行状态失败。");
      }
    };
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [runDetail?.runId, runDetail?.status]);

  const availableFeatureColumns = useMemo(() => {
    if (!profile) return [];
    return workflowType === "clustering"
      ? profile.columns.filter((column) => column.inferredType === "number" && !column.isConstant && !column.isPotentialIdentifier)
      : profile.columns.filter((column) => column.name !== targetColumn && !column.isConstant && !column.isPotentialIdentifier && ["number", "string", "boolean"].includes(column.inferredType));
  }, [profile, targetColumn, workflowType]);

  const previousCompletedRun = useMemo(() => {
    if (!runDetail) return null;
    return runHistory.find((item) => item.runId !== runDetail.runId && item.status === "completed") ?? null;
  }, [runDetail, runHistory]);

  function applyRunConfig(source: WorkflowRunDetail) {
    setExperimentName(String(source.configSummary?.experimentName ?? source.experimentName ?? experimentName));
    if (workflowType === "supervised_ml") {
      setTargetColumn(String(source.configSummary?.targetColumn ?? targetColumn));
    } else if (typeof source.configSummary?.clusterCount === "number") {
      setClusterCount(source.configSummary.clusterCount);
    }
    if (Array.isArray(source.configSummary?.featureColumns)) {
      setSelectedFeatures(source.configSummary.featureColumns.map(String));
    }
  }

  async function handleStart() {
    if (!upload || !selectedSheet || !workflowType) return;
    setRunning(true);
    setError(null);
    try {
      const detail =
        workflowType === "supervised_ml"
          ? await startSupervisedWorkflow({
              uploadId: upload.uploadId,
              sheetName: selectedSheet.sheetName,
              experimentName,
              targetColumn,
              featureColumns: selectedFeatures,
              groupingColumns: [],
              timeColumn: null,
              clusterCount: null,
            })
          : await startClusteringWorkflow({
              uploadId: upload.uploadId,
              sheetName: selectedSheet.sheetName,
              experimentName,
              targetColumn: null,
              featureColumns: selectedFeatures,
              groupingColumns: [],
              timeColumn: null,
              clusterCount,
            });
      setRunDetail(detail);
      setRunEvents([]);
      setRunHistory((current) => upsertRun(current, detail));
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动 workflow 失败。");
    } finally {
      setRunning(false);
    }
  }

  async function handleCancel() {
    if (!runDetail?.runId) return;
    setCancelling(true);
    setError(null);
    try {
      await cancelAnalysisRun(runDetail.runId);
      const [detail, events] = await Promise.all([fetchAnalysisRun(runDetail.runId), fetchAnalysisRunEvents(runDetail.runId)]);
      setRunDetail(detail);
      setRunEvents(events.events);
      setRunHistory((current) => upsertRun(current, detail));
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消 workflow 失败。");
    } finally {
      setCancelling(false);
    }
  }

  function toggleFeature(column: string) {
    setSelectedFeatures((current) => (
      current.includes(column) ? current.filter((item) => item !== column) : [...current, column]
    ));
  }

  if (!workflowType) {
    return <EmptyState title="当前 workflow 地址无效" detail="请回到 /analysis 重新选择监督学习或聚类 workflow。" />;
  }

  if (!upload || !selectedSheet) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={workflowLabel(workflowType)}
          title="还没有可配置的数据"
          description="先在上传页导入数据，再从 /analysis 进入正式 workflow。"
          action={<button type="button" className={controls.primaryButton} onClick={() => navigate("/upload")}>去上传数据</button>}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={workflowLabel(workflowType)}
        title={workflowType === "supervised_ml" ? "可配置监督学习工作流" : "可配置聚类工作流"}
        description={workflowType === "supervised_ml"
          ? "这里不再只是‘可启动’，而是可以配置目标列、特征列，观察运行阶段，并用同一套配置反复重跑。"
          : "这里可以手动选择聚类特征、簇数，观察运行过程，并基于当前配置持续复跑。"}
        action={
          <div className="flex flex-wrap gap-2">
            <Link className={controls.secondaryButton} to="/analysis">返回分析工作台</Link>
            {runDetail?.experimentId ? (
              <Link className={controls.secondaryButton} to={`/experiments/${runDetail.experimentId}`}>查看实验详情</Link>
            ) : null}
          </div>
        }
      />

      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label="正在加载 workflow 配置上下文..." /> : null}

      {profile ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <StatCard label="Readiness" value={profile.readinessScore.overall} hint={profile.readinessScore.summary} tone={profile.readinessScore.overall >= 70 ? "good" : "warn"} />
            <StatCard label="目标候选" value={profile.targetCandidates[0] ?? "未识别"} hint={`${profile.targetCandidates.length} 个候选`} tone="info" />
            <StatCard label="当前特征选择" value={selectedFeatures.length} hint={workflowType === "clustering" ? "聚类特征数" : "监督学习特征数"} tone="good" />
            <StatCard label="运行状态" value={runDetail?.status ?? "未启动"} hint={runDetail?.summary ?? "等待你确认配置后启动"} tone={runDetail ? detailTone(runDetail.status) : "neutral"} />
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(360px,1.05fr)]">
            <SectionCard
              title="Workflow 配置"
              description={locationState.openedByAgent ? "这是 Agent 根据当前数据建议你优先打开的工作流；你仍然可以手动改配置。" : "先把配置调清楚，再启动正式 workflow。"}
              action={
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={controls.primaryButton} onClick={() => void handleStart()} disabled={running}>
                    {running ? "启动中..." : runDetail?.rerunSupported ? "启动 / 复跑当前配置" : "启动 workflow"}
                  </button>
                  {runDetail && (runDetail.status === "running" || runDetail.status === "planned") ? (
                    <button type="button" className={controls.secondaryButton} onClick={() => void handleCancel()} disabled={cancelling}>
                      {cancelling ? "取消中..." : "停止当前运行"}
                    </button>
                  ) : null}
                </div>
              }
            >
              <div className="space-y-5">
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-slate-900 dark:text-white">实验名称</span>
                  <input className={`${controls.input} bg-white dark:bg-[#111827]`} value={experimentName} onChange={(event) => setExperimentName(event.target.value)} />
                </label>

                {workflowType === "supervised_ml" ? (
                  <label className="block space-y-2">
                    <span className="text-sm font-medium text-slate-900 dark:text-white">目标列</span>
                    <select className={`${controls.input} bg-white dark:bg-[#111827]`} value={targetColumn} onChange={(event) => setTargetColumn(event.target.value)}>
                      {profile.targetCandidates.map((column) => <option key={column} value={column}>{column}</option>)}
                    </select>
                  </label>
                ) : (
                  <label className="block space-y-2">
                    <span className="text-sm font-medium text-slate-900 dark:text-white">簇数</span>
                    <input
                      type="range"
                      min={2}
                      max={8}
                      value={clusterCount}
                      onChange={(event) => setClusterCount(Number(event.target.value))}
                      className="w-full accent-cyan-500"
                    />
                    <div className="text-sm text-slate-600 dark:text-slate-300">当前聚成 {clusterCount} 簇</div>
                  </label>
                )}

                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-slate-900 dark:text-white">特征列</div>
                    <Badge tone="info">已选择 {selectedFeatures.length} 列</Badge>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {availableFeatureColumns.map((column, index) => {
                      const selected = selectedFeatures.includes(column.name);
                      return (
                        <label
                          key={column.name}
                          className={`analysis-card-rise flex items-start gap-3 rounded-2xl border p-3 transition ${
                            selected
                              ? "border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10"
                              : "border-slate-200 bg-white dark:border-white/10 dark:bg-[#151b2e]"
                          }`}
                          style={{ animationDelay: `${index * 55}ms` }}
                        >
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleFeature(column.name)}
                            className="mt-1 h-4 w-4 accent-cyan-500"
                          />
                          <div className="min-w-0">
                            <div className="font-medium text-slate-900 dark:text-white">{column.name}</div>
                            <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                              {column.inferredType} · {column.roleHints.join(" / ") || "feature"}
                            </div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-3">
                  <div className={`${surface.softPanel} p-4`}>
                    <div className={`text-xs ${surface.mutedText}`}>当前配置摘要</div>
                    <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>
                      {workflowType === "supervised_ml"
                        ? `目标列 ${targetColumn || "未选择"}，已选 ${selectedFeatures.length} 个特征。`
                        : `聚成 ${clusterCount} 簇，已选 ${selectedFeatures.length} 个聚类特征。`}
                    </div>
                  </div>
                  <div className={`${surface.softPanel} p-4`}>
                    <div className={`text-xs ${surface.mutedText}`}>观测重点</div>
                    <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>
                      {workflowType === "supervised_ml"
                        ? "重点看训练阶段、评估指标和上一轮特征配置差异。"
                        : "重点看标准化、簇概览和不同簇数的稳定性。"}
                    </div>
                  </div>
                  <div className={`${surface.softPanel} p-4`}>
                    <div className={`text-xs ${surface.mutedText}`}>复跑方式</div>
                    <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>
                      改完配置后直接复跑；下面的运行记录也可以一键回填配置。
                    </div>
                  </div>
                </div>
              </div>
            </SectionCard>

            <SectionCard title="运行观察台" description="运行开始后，这里会持续刷新阶段、进度和事件，直到可回放结果生成。">
              {runDetail ? (
                <div className="space-y-5">
                  <div className="rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-lg font-semibold text-slate-950 dark:text-white">{runDetail.experimentName ?? workflowLabel(workflowType)}</div>
                        <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{runDetail.summary}</div>
                      </div>
                      <Badge tone={detailTone(runDetail.status)}>
                        <span className={runDetail.status === "running" ? "analysis-live-dot" : ""}>{runDetail.status}</span>
                      </Badge>
                    </div>

                    <div className="mt-4">
                      <div className="flex items-center justify-between gap-3 text-sm text-slate-600 dark:text-slate-300">
                        <span>当前阶段：{runDetail.currentStage ?? "等待刷新"}</span>
                        <span>{runDetail.progressPercent}%</span>
                      </div>
                      <div className="analysis-progress-shell mt-2 h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                        <div
                          className="analysis-progress-fill h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700"
                          style={{ width: `${Math.max(runDetail.progressPercent, 4)}%` }}
                        />
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      <div className={`${surface.softPanel} p-4`}>
                        <div className={`text-xs ${surface.mutedText}`}>已完成阶段</div>
                        <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>
                          {runDetail.stages.filter((stage) => stage.status === "completed").length}/{runDetail.stages.length}
                        </div>
                      </div>
                      <div className={`${surface.softPanel} p-4`}>
                        <div className={`text-xs ${surface.mutedText}`}>事件流</div>
                        <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>{runEvents.length}</div>
                      </div>
                      <div className={`${surface.softPanel} p-4`}>
                        <div className={`text-xs ${surface.mutedText}`}>是否可复跑</div>
                        <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>{runDetail.rerunSupported ? "是" : "否"}</div>
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-3">
                    {runDetail.stages.map((stage, index) => (
                      <div
                        key={stage.stageId}
                        className={`analysis-card-rise rounded-2xl border p-4 transition ${
                          stage.status === "completed"
                            ? "border-emerald-300 bg-emerald-50 dark:border-emerald-400/20 dark:bg-emerald-400/10"
                            : stage.status === "running"
                              ? "border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10"
                            : "border-slate-200 bg-white dark:border-white/10 dark:bg-[#151b2e]"
                        }`}
                        style={{ animationDelay: `${index * 80}ms` }}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <div className="font-semibold text-slate-950 dark:text-white">{stage.title}</div>
                            <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{stage.description}</div>
                          </div>
                          <Badge tone={stageTone(stage.status)}>
                            <span className={stage.status === "running" ? "analysis-live-dot" : ""}>{stage.status}</span>
                          </Badge>
                        </div>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                          <div
                            className={`${stage.status === "running" ? "analysis-progress-fill" : ""} h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700`}
                            style={{ width: `${Math.max(stage.progressPercent, stage.status === "running" ? 8 : 0)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <SectionCard title="运行事件" description="这是当前 workflow 的阶段性回放。">
                      <div className="space-y-3">
                        {runEvents.length ? runEvents.map((event) => (
                          <div key={event.eventId} className="rounded-2xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="font-medium text-slate-900 dark:text-white">{event.title}</div>
                              <Badge tone={event.status === "completed" ? "good" : event.status === "failed" ? "bad" : "info"}>{event.status}</Badge>
                            </div>
                            <div className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{event.detail}</div>
                          </div>
                        )) : <div className="text-sm text-slate-500 dark:text-slate-400">正在等待第一批运行事件...</div>}
                      </div>
                    </SectionCard>

                    <SectionCard title="配置与结果快照" description="复跑时会沿用这里的配置摘要；运行完成后也会显示首轮结果。">
                      <div className="space-y-3">
                        <div className={`${surface.softPanel} p-4`}>
                          <div className={`text-xs ${surface.mutedText}`}>配置摘要</div>
                          <div className={`mt-2 space-y-1 text-sm ${surface.strongText}`}>
                            {Object.entries(runDetail.configSummary ?? {}).map(([key, value]) => (
                              <div key={key}>{key}: {Array.isArray(value) ? value.join("、") : formatMetricValue(value)}</div>
                            ))}
                          </div>
                        </div>
                        <div className={`${surface.softPanel} p-4`}>
                          <div className={`text-xs ${surface.mutedText}`}>结果摘要</div>
                          <div className={`mt-2 space-y-1 text-sm ${surface.strongText}`}>
                            {Object.keys(runDetail.metricsSummary ?? {}).length ? (
                              Object.entries(runDetail.metricsSummary ?? {}).map(([key, value]) => (
                                <div key={key}>{key}: {formatMetricValue(value)}</div>
                              ))
                            ) : (
                              <div>等待运行完成后生成。</div>
                            )}
                          </div>
                        </div>
                        {runDetail.warnings.length ? (
                          <div className="flex flex-wrap gap-2">
                            {runDetail.warnings.map((warning) => <Badge key={warning} tone="warn">{warning}</Badge>)}
                          </div>
                        ) : null}
                        {previousCompletedRun ? (
                          <div className="rounded-2xl border border-cyan-200 bg-cyan-50 p-4 dark:border-cyan-400/20 dark:bg-cyan-400/10">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="text-sm font-semibold text-slate-950 dark:text-white">与上一轮完成结果对比</div>
                              <button type="button" className={controls.secondaryButton} onClick={() => applyRunConfig(previousCompletedRun)}>
                                套用上一轮配置
                              </button>
                            </div>
                            <div className="mt-3 grid gap-3 md:grid-cols-2">
                              <div className={`${surface.softPanel} p-3`}>
                                <div className={`text-xs ${surface.mutedText}`}>上一轮</div>
                                <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>
                                  {Object.entries(previousCompletedRun.metricsSummary ?? {}).slice(0, 3).map(([key, value]) => (
                                    <div key={key}>{key}: {formatMetricValue(value)}</div>
                                  ))}
                                </div>
                              </div>
                              <div className={`${surface.softPanel} p-3`}>
                                <div className={`text-xs ${surface.mutedText}`}>本轮</div>
                                <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>
                                  {Object.entries(runDetail.metricsSummary ?? {}).slice(0, 3).map(([key, value]) => (
                                    <div key={key}>{key}: {formatMetricValue(value)}</div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </SectionCard>
                  </div>

                  <SectionCard title="复跑记录" description="每次启动或复跑都会在这里留下一个可回填配置的记录。">
                    <div className="space-y-3">
                      {runHistory.length ? runHistory.map((item, index) => (
                        <div
                          key={item.runId}
                          className="analysis-card-rise rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]"
                          style={{ animationDelay: `${index * 70}ms` }}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="font-semibold text-slate-950 dark:text-white">{item.experimentName ?? item.runId}</div>
                              <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{item.summary}</div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              <Badge tone={detailTone(item.status)}>{item.status}</Badge>
                              <button type="button" className={controls.secondaryButton} onClick={() => applyRunConfig(item)}>
                                用这轮配置
                              </button>
                            </div>
                          </div>
                          <div className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                            特征 {Array.isArray(item.configSummary?.featureColumns) ? item.configSummary.featureColumns.length : 0} 个
                            {workflowType === "supervised_ml" ? ` · 目标 ${item.configSummary?.targetColumn ?? "-"}` : ` · 簇数 ${item.configSummary?.clusterCount ?? "-"}`}
                          </div>
                        </div>
                      )) : (
                        <div className="text-sm text-slate-500 dark:text-slate-400">还没有复跑记录，启动一次后这里就会形成可回填历史。</div>
                      )}
                    </div>
                  </SectionCard>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm leading-6 text-slate-600 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-300">
                    这里会在你点击“启动 / 复跑当前配置”后，实时显示阶段进度、事件回放、配置摘要与结果摘要。
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="analysis-skeleton rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">阶段进度</div>
                      <div className="mt-3 h-3 rounded-full bg-slate-200 dark:bg-white/10" />
                    </div>
                    <div className="analysis-skeleton rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">运行事件</div>
                      <div className="mt-3 h-3 rounded-full bg-slate-200 dark:bg-white/10" />
                    </div>
                    <div className="analysis-skeleton rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">结果摘要</div>
                      <div className="mt-3 h-3 rounded-full bg-slate-200 dark:bg-white/10" />
                    </div>
                  </div>
                </div>
              )}
            </SectionCard>
          </div>
        </>
      ) : null}
    </div>
  );
}
