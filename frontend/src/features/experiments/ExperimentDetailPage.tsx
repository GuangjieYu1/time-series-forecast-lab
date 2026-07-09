import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { fetchExperiment, manifestDownloadUrl, prepareExperimentRerun } from "../../shared/api/client";
import { useLabStore } from "../../app/store";
import { DataTable } from "../../shared/components/Table";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface, Tabs } from "../../shared/components/Ui";
import type { ExperimentDetail, ForecastRunResponse } from "../../shared/types/api";
import { AttributionAgentDrawer, type AgentLaunchRequest } from "../attribution/AttributionAgentDrawer";
import { AttributionSnapshotPanel } from "../attribution/AttributionSnapshotPanel";
import {
  AbsoluteErrorTimelineChart,
  ActualVsPredictedChart,
  FinalForecastChart,
  MetricBarChart,
  NormalizedMetricChart,
  PredictedResidualScatterChart,
  ResidualDistributionChart,
  ResidualTimelineChart
} from "../visualization/Charts";
import { ReportPanel } from "../reports/ReportPanel";
import { DataHealthPanel } from "../forecast/DataHealthPanel";
import { ModelLeaderboard } from "../forecast/ModelLeaderboard";
import { ExplainabilityPanel } from "../runtime/ExplainabilityPanel";
import { FeatureFactoryPanel } from "../runtime/FeatureFactoryPanel";
import { RuntimeModelConsoleDrawer } from "../runtime/RuntimeModelConsoleDrawer";
import { RuntimeInspectorPanel } from "../runtime/RuntimeInspectorPanel";

type DetailTab = "runtime" | "featureFactory" | "explainability" | "attribution" | "dataHealth" | "overview" | "residual" | "metrics" | "distribution" | "final" | "report";

function asForecastResult(experiment: ExperimentDetail): ForecastRunResponse {
  return {
    experimentId: experiment.experimentId,
    targetColumn: experiment.targetColumn,
    detectedFrequency: String((experiment.dataProfile.targets as Array<Record<string, unknown>> | undefined)?.[0]?.detectedFrequency ?? "D"),
    horizon: Number((experiment.config.horizon as number | undefined) ?? 1),
    testSize: Number((experiment.config.testSize as number | undefined) ?? 1),
    recommendedModelId: experiment.recommendedModelId,
    rankedModels: experiment.rankedModels,
    backtest: experiment.backtest,
    diagnostics: experiment.diagnostics,
    dataHealth: experiment.dataHealth ?? {
      score: 0,
      level: "poor",
      warnings: [],
      suggestions: [],
      diagnostics: {
        frequency: null,
        validPointCount: 0,
        trainPointCount: 0,
        testPointCount: 0,
        originalRowCount: 0,
        droppedRowRate: 0,
        invalidTimeRate: 0,
        targetMissingRate: 0,
        duplicateTimeRate: 0,
        missingTimeRate: 0,
        outlierRate: 0,
        continuityCoverage: 0,
        timeContinuous: true,
        trainSizeSufficient: true,
        testSizeReasonable: true,
        timeStart: null,
        timeEnd: null,
        timeSpanDays: null
      }
    },
    targetResults: [],
    manifest: experiment.manifest,
  };
}

export function ExperimentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { beginRerunDraft, selectedWorkspaceId, workspaces } = useLabStore();
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<DetailTab>("runtime");
  const [copyState, setCopyState] = useState<"idle" | "done" | "failed">("idle");
  const [selectedRuntimeModelKey, setSelectedRuntimeModelKey] = useState("");
  const [agentOpen, setAgentOpen] = useState(false);
  const [launchRequest, setLaunchRequest] = useState<AgentLaunchRequest | null>(null);
  const selectedWorkspace = workspaces.find((item) => item.workspaceId === selectedWorkspaceId) ?? null;

  useEffect(() => {
    if (!id) return;
    const experimentId = id;
    async function load() {
      setLoading(true);
      setError(null);
      setActionError(null);
      try {
        setExperiment(await fetchExperiment(experimentId));
      } catch (err) {
        setError(err instanceof Error ? err.message : "实验详情加载失败。");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [id, selectedWorkspaceId]);

  if (loading) return <LoadingBlock label="正在加载实验详情..." />;
  if (error) return <ErrorBanner message={error} />;
  if (!experiment) return <EmptyState title="没有找到这个实验" detail="历史记录可能已被删除，或实验 ID 不存在。" />;

  const result = asForecastResult(experiment);
  const successfulModels = experiment.rankedModels.filter((model) => model.status === "success").length;
  const failedModels = experiment.rankedModels.length - successfulModels;
  const best = experiment.rankedModels.find((model) => model.rank === 1 && model.metrics);

  async function handleCopyHash() {
    const currentExperiment = experiment;
    if (!currentExperiment?.configHash) return;
    try {
      await navigator.clipboard.writeText(currentExperiment.configHash);
      setCopyState("done");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("failed");
    }
  }

  async function handleRerun() {
    if (!experiment) return;
    try {
      const draft = await prepareExperimentRerun(experiment.experimentId);
      beginRerunDraft(draft);
      navigate("/upload");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "重跑模板准备失败。");
    }
  }

  function askAgent(prompt: string) {
    setAgentOpen(true);
    setLaunchRequest({
      prompt,
      nonce: `${Date.now()}_${Math.random().toString(16).slice(2)}`
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="实验详情"
        title={experiment.experimentName}
        description={`${experiment.fileName} / ${experiment.sheetName} / 目标列：${experiment.targetColumn}`}
        action={
          <div className="flex flex-wrap gap-2">
            <Link className={controls.secondaryButton} to="/experiments">
              返回历史
            </Link>
            <Link className={controls.secondaryButton} to={`/experiments/${experiment.experimentId}/attribution`}>
              Attribution Lab
            </Link>
            <button type="button" className={controls.primaryButton} onClick={() => setAgentOpen(true)}>
              归因 Agent
            </button>
          </div>
        }
      />
      <ErrorBanner message={actionError} />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="推荐模型" value={experiment.recommendedModelId ?? "暂无"} hint="默认按 MAE 最低推荐" tone="good" />
        <StatCard label="最佳 MAE" value={experiment.bestMae === null ? "-" : experiment.bestMae.toFixed(2)} hint="越低越好" tone="info" />
        <StatCard label="成功模型" value={successfulModels} hint={`失败模型 ${failedModels} 个`} />
        <StatCard label="创建时间" value={new Date(experiment.createdAt).toLocaleString()} hint="详情不依赖原始文件" />
      </div>

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard className="min-w-0 overflow-hidden" title="历史回放驾驶舱" description="这里使用数据库保存的排行榜、预测点和图表摘要，不重新读取上传文件。">
          <Tabs<DetailTab>
            value={tab}
            onChange={setTab}
            items={[
              { id: "runtime", label: "透明引擎" },
              { id: "featureFactory", label: "Feature Factory" },
              { id: "explainability", label: "特征解释" },
              { id: "attribution", label: "归因实验室" },
              { id: "dataHealth", label: "数据健康" },
              { id: "overview", label: "预测对比" },
              { id: "residual", label: "残差诊断" },
              { id: "metrics", label: "指标排名" },
              { id: "distribution", label: "误差分布" },
              { id: "final", label: "最终预测" },
              { id: "report", label: "AI 报告" }
            ]}
          />

          <div className="mt-5">
            {tab === "runtime" ? (
              <div className="space-y-4">
                {experiment.runtime?.models.length ? (
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {experiment.runtime.models.map((model) => {
                      const key = `${model.targetColumn}:${model.modelId}`;
                      const active = selectedRuntimeModelKey === key;
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setSelectedRuntimeModelKey((current) => (current === key ? "" : key))}
                          className={`rounded-2xl border p-4 text-left transition ${
                            active
                              ? "border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10"
                              : "border-slate-200 bg-white hover:border-slate-300 dark:border-white/10 dark:bg-[#151b2e]"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="font-semibold text-slate-950 dark:text-white">{model.modelName}</div>
                              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{model.targetColumn}</div>
                            </div>
                            <Badge tone={model.status === "success" ? "good" : model.status === "failed" ? "bad" : "info"}>
                              {model.progressPercent}%
                            </Badge>
                          </div>
                          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                            <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400" style={{ width: `${model.progressPercent}%` }} />
                          </div>
                          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">{active ? "点击收起右侧 Drawer" : "点击打开右侧 Drawer"}</div>
                        </button>
                      );
                    })}
                  </div>
                ) : null}

                <RuntimeInspectorPanel
                  runtime={experiment.runtime}
                  title="Transparent Experiment Engine Replay"
                  description="这里回放的是实验落库后的 runtime 快照：状态机、特征管线、优化过程和日志都可以直接追溯。"
                />
                <RuntimeModelConsoleDrawer
                  runtime={experiment.runtime}
                  selectedModelKey={selectedRuntimeModelKey}
                  open={Boolean(selectedRuntimeModelKey)}
                  onClose={() => setSelectedRuntimeModelKey("")}
                />
              </div>
            ) : null}

            {tab === "featureFactory" ? (
              <FeatureFactoryPanel
                experimentId={experiment.experimentId}
                initialTargets={experiment.runtime?.featurePipeline ?? []}
              />
            ) : null}

            {tab === "explainability" ? (
              <ExplainabilityPanel
                experimentId={experiment.experimentId}
                recommendedModelId={experiment.recommendedModelId}
                initialPayload={experiment.explainability}
              />
            ) : null}

            {tab === "attribution" ? (
              <AttributionSnapshotPanel
                attribution={experiment.attribution}
                onAskAgent={askAgent}
                heading="Attribution Lab"
                description="这里把当前实验的归因证据整理成 5 个主区块，每个区块都可以继续交给右侧 Agent 深挖。"
              />
            ) : null}

            {tab === "dataHealth" ? <DataHealthPanel dataHealth={experiment.dataHealth} /> : null}

            {tab === "overview" ? (
              <div className="grid gap-5">
                <div className={`${surface.chartPanel} p-3`}>
                  <ActualVsPredictedChart result={result} height={430} />
                </div>
                <div className={`${surface.chartPanel} p-3`}>
                  <MetricBarChart result={result} metric="mae" />
                </div>
              </div>
            ) : null}

            {tab === "residual" ? (
              <div className="grid gap-5 xl:grid-cols-2">
                <div className={`${surface.chartPanel} p-3 xl:col-span-2`}>
                  <ResidualTimelineChart result={result} />
                </div>
                <div className={`${surface.chartPanel} p-3`}>
                  <AbsoluteErrorTimelineChart result={result} />
                </div>
                <div className={`${surface.chartPanel} p-3`}>
                  <PredictedResidualScatterChart result={result} />
                </div>
              </div>
            ) : null}

            {tab === "metrics" ? (
              <div className="grid gap-5">
                <ModelLeaderboard rows={experiment.rankedModels} recommendedModelId={experiment.recommendedModelId} />
                <div className={`${surface.chartPanel} p-3`}>
                  <NormalizedMetricChart result={result} />
                </div>
              </div>
            ) : null}

            {tab === "distribution" ? (
              <div className={`${surface.chartPanel} p-3`}>
                <ResidualDistributionChart result={result} />
              </div>
            ) : null}

            {tab === "final" ? (
              <div className={`${surface.chartPanel} p-3`}>
                <FinalForecastChart finalForecast={experiment.finalForecast} />
              </div>
            ) : null}

            {tab === "report" ? (
              <ReportPanel
                experimentId={experiment.experimentId}
                initialReports={experiment.reports}
                visualization={{
                  result,
                  finalForecast: experiment.finalForecast,
                  metric: "mae"
                }}
              />
            ) : null}
          </div>
        </SectionCard>

        <div className="min-w-0 space-y-5">
          <SectionCard title="推荐结论" description="系统推荐仍以 holdout 测试集 MAE 排名为准。">
            <div className={`${surface.softPanel} p-4`}>
              <div className={`text-sm ${surface.mutedText}`}>最佳模型</div>
              <div className={`mt-2 text-2xl font-semibold ${surface.strongText}`}>{best?.modelName ?? experiment.recommendedModelId ?? "-"}</div>
              <p className={`mt-3 text-sm leading-6 ${surface.mutedText}`}>
                推荐原因：测试集 MAE 最低。失败模型保留在历史状态中，但不参与推荐与默认图表展示。
              </p>
            </div>
          </SectionCard>

          <SectionCard title="诊断信息" description="后端保存的实验摘要。">
            <pre className="max-h-96 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
              {JSON.stringify(experiment.diagnostics, null, 2)}
            </pre>
          </SectionCard>


        </div>
      </div>

      <SectionCard
        title="实验可复现"
        description="配置 hash、源文件 hash 和运行环境都会跟随实验一起保存。"
        action={
          <div className="flex flex-wrap gap-2">
            <button className={controls.secondaryButton} onClick={() => window.open(manifestDownloadUrl(experiment.experimentId), "_blank")}>
              下载 Manifest
            </button>
            <button className={controls.secondaryButton} onClick={() => void handleCopyHash()}>
              {copyState === "done" ? "已复制 Hash" : copyState === "failed" ? "复制失败" : "复制 Hash"}
            </button>
            <button
              className={controls.primaryButton}
              disabled={selectedWorkspace?.isReadOnly}
              title={selectedWorkspace?.isReadOnly ? "Example 工作区是只读空间，不能重新运行实验。" : undefined}
              onClick={() => void handleRerun()}
            >
              {selectedWorkspace?.isReadOnly ? "Example 只读" : "重新运行实验"}
            </button>
          </div>
        }
      >
        <div className="grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-3">
          {[
            ["配置 Hash", experiment.configHash ?? "-"],
            ["源文件 Hash", experiment.sourceFileSha256 ?? "-"],
            ["随机种子", String((experiment.manifest?.configuration.randomSeed as number | undefined) ?? 42)],
            ["运行模式", String((experiment.manifest?.configuration.runProfile as string | undefined) ?? "balanced")],
            ["参数策略", String((experiment.manifest?.configuration.parameterStrategy as string | undefined) ?? "default")],
            ["应用版本", experiment.appVersion ?? experiment.manifest?.environment.appVersion ?? "-"],
            ["Git Commit", experiment.gitCommit ?? experiment.manifest?.environment.gitCommit ?? "-"],
            ["运行设备", experiment.manifest?.environment.device ?? "-"],
            ["Python 版本", experiment.manifest?.environment.pythonVersion ?? "-"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
              <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
              <div className="mt-2 break-all font-medium text-slate-900 dark:text-white">{value}</div>
            </div>
          ))}
        </div>
      </SectionCard>

      <AttributionAgentDrawer
        open={agentOpen}
        onClose={() => setAgentOpen(false)}
        experimentId={experiment.experimentId}
        experiment={experiment}
        currentPage="/experiments/:id"
        currentTab={tab}
        selectedModelId={selectedRuntimeModelKey ? selectedRuntimeModelKey.split(":")[1] ?? null : experiment.recommendedModelId}
        historySummary={experiment.agentHistorySummary}
        availableSkills={experiment.availableAgentSkills}
        attribution={experiment.attribution}
        launchRequest={launchRequest}
      />
    </div>
  );
}
