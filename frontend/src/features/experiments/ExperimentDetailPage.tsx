import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { fetchExperiment, prepareExperimentRerun } from "../../shared/api/client";
import { useLabStore } from "../../app/store";
import { DataTable } from "../../shared/components/Table";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface, Tabs } from "../../shared/components/Ui";
import type { ExperimentDetail, ForecastRunResponse, RankedModel } from "../../shared/types/api";
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

type DetailTab = "dataHealth" | "overview" | "residual" | "metrics" | "distribution" | "final" | "report";

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

function metricText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value < 1 ? value.toFixed(4) : value.toFixed(2);
}

function Leaderboard({ rows, recommendedModelId }: { rows: RankedModel[]; recommendedModelId: string | null }) {
  return (
    <DataTable<RankedModel>
      data={rows}
      columns={[
        { header: "排名", cell: ({ row }) => row.original.rank ?? "-" },
        { header: "模型", cell: ({ row }) => row.original.modelName },
        { header: "MAE", cell: ({ row }) => metricText(row.original.metrics?.mae) },
        { header: "RMSE", cell: ({ row }) => metricText(row.original.metrics?.rmse) },
        { header: "WAPE", cell: ({ row }) => metricText(row.original.metrics?.wape) },
        { header: "推荐", cell: ({ row }) => (row.original.modelId === recommendedModelId ? <Badge tone="good">推荐模型</Badge> : null) },
        {
          header: "状态",
          cell: ({ row }) =>
            row.original.status === "success" ? <Badge tone="good">成功</Badge> : <Badge tone="bad">{row.original.error ?? "失败"}</Badge>
        }
      ]}
    />
  );
}

export function ExperimentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { beginRerunDraft } = useLabStore();
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<DetailTab>("dataHealth");
  const [copyState, setCopyState] = useState<"idle" | "done" | "failed">("idle");

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
  }, [id]);

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

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="实验详情"
        title={experiment.experimentName}
        description={`${experiment.fileName} / ${experiment.sheetName} / 目标列：${experiment.targetColumn}`}
        action={
          <Link className={controls.secondaryButton} to="/experiments">
            返回历史
          </Link>
        }
      />
      <ErrorBanner message={actionError} />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="推荐模型" value={experiment.recommendedModelId ?? "暂无"} hint="默认按 MAE 最低推荐" tone="good" />
        <StatCard label="最佳 MAE" value={experiment.bestMae === null ? "-" : experiment.bestMae.toFixed(2)} hint="越低越好" tone="info" />
        <StatCard label="成功模型" value={successfulModels} hint={`失败模型 ${failedModels} 个`} />
        <StatCard label="创建时间" value={new Date(experiment.createdAt).toLocaleString()} hint="详情不依赖原始文件" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <SectionCard title="历史回放驾驶舱" description="这里使用数据库保存的排行榜、预测点和图表摘要，不重新读取上传文件。">
          <Tabs<DetailTab>
            value={tab}
            onChange={setTab}
            items={[
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
                <Leaderboard rows={experiment.rankedModels} recommendedModelId={experiment.recommendedModelId} />
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

            {tab === "report" ? <ReportPanel experimentId={experiment.experimentId} initialReports={experiment.reports} /> : null}
          </div>
        </SectionCard>

        <div className="space-y-5">
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

          <SectionCard
            title="实验可复现"
            description="配置 hash、源文件 hash 和运行环境都会跟随实验一起保存。"
            action={
              <div className="flex flex-wrap gap-2">
                <button className={controls.secondaryButton} onClick={() => window.open(`/api/experiments/${experiment.experimentId}/manifest/download`, "_blank")}>
                  下载 Manifest
                </button>
                <button className={controls.secondaryButton} onClick={() => void handleCopyHash()}>
                  {copyState === "done" ? "已复制 Hash" : copyState === "failed" ? "复制失败" : "复制 Hash"}
                </button>
                <button className={controls.primaryButton} onClick={() => void handleRerun()}>
                  重新运行实验
                </button>
              </div>
            }
          >
            <div className="grid gap-3 text-sm md:grid-cols-2">
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
        </div>
      </div>
    </div>
  );
}
