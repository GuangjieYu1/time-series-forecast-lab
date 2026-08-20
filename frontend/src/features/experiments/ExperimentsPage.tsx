import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useLabStore } from "../../app/store";
import { deleteExperiment, fetchExperiments, moveExperiment } from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, StatCard } from "../../shared/components/Ui";
import type { ExperimentListItem } from "../../shared/types/api";

export function ExperimentsPage() {
  const { currentUser, selectedWorkspaceId, workspaces } = useLabStore();
  const [experiments, setExperiments] = useState<ExperimentListItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [moveTargets, setMoveTargets] = useState<Record<string, string>>({});
  const selectedWorkspace = workspaces.find((item) => item.workspaceId === selectedWorkspaceId) ?? null;
  const writableTargets = workspaces.filter((workspace) => workspace.workspaceId !== selectedWorkspaceId && workspace.canWrite && !workspace.isReadOnly);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setExperiments(await fetchExperiments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "实验历史加载失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [selectedWorkspaceId]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return experiments;
    return experiments.filter((item) => [item.experimentName, item.fileName, item.sheetName, item.targetColumn, item.recommendedModelId ?? ""].join(" ").toLowerCase().includes(needle));
  }, [experiments, query]);

  async function remove(id: string) {
    try {
      await deleteExperiment(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除实验失败。");
    }
  }

  function canManage(experiment: ExperimentListItem) {
    return experiment.createdByUserId === currentUser?.userId || selectedWorkspace?.role === "owner" || selectedWorkspace?.role === "manager" || selectedWorkspace?.role === "admin";
  }

  async function move(experimentId: string) {
    const targetWorkspaceId = moveTargets[experimentId];
    if (!targetWorkspaceId) return;
    try {
      await moveExperiment(experimentId, targetWorkspaceId);
      setMoveTargets((current) => ({ ...current, [experimentId]: "" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移动项目失败。");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="实验历史"
        title="预测实验项目列表"
        description="历史记录保存配置、指标、图表数据、最终预测和 AI 报告，不依赖原始上传文件。"
        action={<input className={`${controls.input} min-w-[280px]`} placeholder="搜索实验、文件、目标列或模型" value={query} onChange={(event) => setQuery(event.target.value)} />}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="实验总数" value={experiments.length} hint="SQLite 历史记录" tone="info" />
        <StatCard label="搜索结果" value={filtered.length} hint="按实验名、文件名、目标列过滤" />
        <StatCard label="最近实验" value={experiments[0]?.recommendedModelId ?? "暂无"} hint="推荐模型" tone="good" />
        <StatCard label="最佳 MAE" value={experiments[0]?.bestMae?.toFixed(2) ?? "-"} hint="最近实验指标" tone="warn" />
      </div>

      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label="正在加载实验历史..." /> : null}
      {!loading && !filtered.length ? <EmptyState title="没有找到实验记录" detail="运行一次预测实验后，这里会展示历史回放入口。" /> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((experiment) => (
          <article key={experiment.experimentId} className="group rounded-3xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-xl hover:shadow-slate-200/70 dark:border-white/10 dark:bg-[#111827] dark:hover:shadow-black/30">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate font-semibold text-slate-950 dark:text-white">{experiment.experimentName}</h3>
                <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">{experiment.fileName} / {experiment.sheetName}</p>
              </div>
              <Badge tone="info">{experiment.modelCount} 个模型</Badge>
            </div>
            <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
                <dt className="text-xs text-slate-400">目标列</dt>
                <dd className="mt-1 truncate font-medium text-slate-700 dark:text-slate-200">{experiment.targetColumn}</dd>
              </div>
              <div className="rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
                <dt className="text-xs text-slate-400">最佳 MAE</dt>
                <dd className="mt-1 font-medium text-slate-700 dark:text-slate-200">{experiment.bestMae?.toFixed(2) ?? "-"}</dd>
              </div>
              <div className="rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
                <dt className="text-xs text-slate-400">推荐模型</dt>
                <dd className="mt-1 truncate font-medium text-slate-700 dark:text-slate-200">{experiment.recommendedModelId ?? "-"}</dd>
              </div>
              <div className="rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
                <dt className="text-xs text-slate-400">创建时间</dt>
                <dd className="mt-1 text-xs font-medium text-slate-700 dark:text-slate-200">{new Date(experiment.createdAt).toLocaleString()}</dd>
              </div>
            </dl>
            {canManage(experiment) && writableTargets.length ? (
              <div className="mt-4 flex gap-2">
                <select className={`${controls.input} min-w-0 flex-1`} value={moveTargets[experiment.experimentId] ?? ""} onChange={(event) => setMoveTargets((current) => ({ ...current, [experiment.experimentId]: event.target.value }))}>
                  <option value="">移动到…</option>
                  {writableTargets.map((workspace) => <option key={workspace.workspaceId} value={workspace.workspaceId}>{workspace.name} · {workspace.kind}</option>)}
                </select>
                <button className={controls.secondaryButton} disabled={!moveTargets[experiment.experimentId]} onClick={() => void move(experiment.experimentId)}>移动</button>
              </div>
            ) : null}
            <div className="mt-5 flex gap-2">
              <Link className={`${controls.primaryButton} flex-1`} to={`/experiments/${experiment.experimentId}`}>
                打开详情
              </Link>
              <button
                className={controls.dangerButton}
                disabled={!canManage(experiment) || selectedWorkspace?.isReadOnly}
                title={!canManage(experiment) ? "只有项目创建者、空间 Owner 或组管理员可以删除。" : selectedWorkspace?.isReadOnly ? "只读工作区不能删除实验。" : undefined}
                onClick={() => void remove(experiment.experimentId)}
              >
                {selectedWorkspace?.isReadOnly ? "只读" : "删除"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
