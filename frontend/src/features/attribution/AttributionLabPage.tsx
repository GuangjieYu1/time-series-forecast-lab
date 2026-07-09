import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchExperiment } from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard } from "../../shared/components/Ui";
import type { ExperimentDetail } from "../../shared/types/api";
import { AttributionAgentDrawer, type AgentLaunchRequest } from "./AttributionAgentDrawer";
import { AttributionSnapshotPanel } from "./AttributionSnapshotPanel";

export function AttributionLabPage() {
  const { id } = useParams();
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [launchRequest, setLaunchRequest] = useState<AgentLaunchRequest | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchExperiment(id)
      .then((detail) => {
        if (cancelled) return;
        setExperiment(detail);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "归因实验室加载失败。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const quickStats = useMemo(() => {
    if (!experiment) return [];
    const best = experiment.rankedModels.find((model) => model.rank === 1 && model.metrics);
    return [
      { label: "目标列", value: experiment.targetColumn, hint: "当前实验上下文" },
      { label: "推荐模型", value: experiment.recommendedModelId ?? "暂无", hint: "回测推荐" },
      { label: "最佳 MAE", value: experiment.bestMae === null ? "-" : experiment.bestMae.toFixed(2), hint: best?.modelName ?? "暂无" },
      { label: "Agent 历史", value: experiment.agentHistorySummary.length, hint: "可回放 run" }
    ];
  }, [experiment]);

  function askAgent(prompt: string) {
    setAgentOpen(true);
    setLaunchRequest({
      prompt,
      nonce: `${Date.now()}_${Math.random().toString(16).slice(2)}`
    });
  }

  if (loading) return <LoadingBlock label="正在加载 Attribution Lab..." />;
  if (error) return <ErrorBanner message={error} />;
  if (!experiment) return <EmptyState title="没有找到这个实验" detail="请先确认实验是否仍存在于当前工作区。" />;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Attribution Lab"
        title={experiment.experimentName}
        description={`${experiment.fileName} / ${experiment.sheetName} / 目标列：${experiment.targetColumn}`}
        action={
          <div className="flex flex-wrap gap-2">
            <Link className={controls.secondaryButton} to={`/experiments/${experiment.experimentId}`}>
              返回实验详情
            </Link>
            <button type="button" className={controls.primaryButton} onClick={() => setAgentOpen(true)}>
              归因 Agent
            </button>
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-4">
        {quickStats.map((item) => <StatCard key={item.label} label={item.label} value={item.value} hint={item.hint} />)}
      </div>

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <AttributionSnapshotPanel attribution={experiment.attribution} onAskAgent={askAgent} heading="归因实验室" description="这里是当前实验的归因快照。每个区块都能直接把上下文交给右侧 Agent 深挖。" />
        </div>

        <div className="space-y-5">
          <SectionCard title="可用 Agent Skills" description="第一版按 read / analysis / action 三层组织。">
            <div className="flex flex-wrap gap-2">
              {experiment.availableAgentSkills.length ? experiment.availableAgentSkills.map((skill) => (
                <Badge key={skill.skillId} tone={skill.category === "read" ? "neutral" : skill.category === "analysis" ? "info" : "warn"}>
                  {skill.skillId}
                </Badge>
              )) : <span className="text-sm text-slate-500 dark:text-slate-400">暂无 skills。</span>}
            </div>
          </SectionCard>

          <SectionCard title="归因入口建议" description="可以直接点下面的快捷追问，带着当前实验上下文发给 Agent。">
            <div className="space-y-2">
              {[
                "这次最主要的下降原因是什么",
                "生成一张管理层可看的瀑布图",
                "只看主要 driver 的贡献排序",
                "把协变量泄漏风险单独总结出来",
                "把当前归因结论整理成报告章节"
              ].map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => askAgent(prompt)}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-200 dark:hover:border-cyan-400/30 dark:hover:text-cyan-200"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </SectionCard>
        </div>
      </div>

      <AttributionAgentDrawer
        open={agentOpen}
        onClose={() => setAgentOpen(false)}
        experimentId={experiment.experimentId}
        experiment={experiment}
        currentPage="/experiments/:id/attribution"
        currentTab="attribution"
        selectedModelId={experiment.recommendedModelId}
        historySummary={experiment.agentHistorySummary}
        availableSkills={experiment.availableAgentSkills}
        attribution={experiment.attribution}
        launchRequest={launchRequest}
      />
    </div>
  );
}
