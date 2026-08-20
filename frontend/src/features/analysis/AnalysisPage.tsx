import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLabStore } from "../../app/store";
import { AnalysisAgentDrawer } from "./AnalysisAgentDrawer";
import {
  executeDatasetTransform,
  fetchAnalysisProfile,
  fetchAnalysisRouteSuggestion,
  planDatasetTransform,
  startAttributionWorkflow,
} from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import type { AnalysisType, DatasetProfile, DatasetRecommendation, DatasetTransformPlan, DatasetTransformResult, DatasetTransformType, RouteSuggestion } from "../../shared/types/api";

const routeLabels: Record<AnalysisType, string> = {
  attribution: "归因分析",
  clustering: "聚类分析",
  forecast: "时间序列预测",
  supervised_ml: "监督学习",
};

const previewableTransforms: DatasetTransformType[] = [
  "drop_constant_columns",
  "drop_identifier_columns",
  "drop_high_missing_columns",
  "normalize_numeric_features",
];

function analysisTone(score: number): "good" | "info" | "warn" | "bad" {
  if (score >= 80) return "good";
  if (score >= 65) return "info";
  if (score >= 50) return "warn";
  return "bad";
}

function isPreviewableTransform(actionType: DatasetRecommendation["actionType"]): actionType is DatasetTransformType {
  return previewableTransforms.includes(actionType as DatasetTransformType);
}

export function AnalysisPage() {
  const navigate = useNavigate();
  const { upload, selectedSheet, setUpload, setSelectedSheet } = useLabStore();
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [routes, setRoutes] = useState<RouteSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startingRoute, setStartingRoute] = useState<AnalysisType | null>(null);
  const [transformPlan, setTransformPlan] = useState<DatasetTransformPlan | null>(null);
  const [transformRequest, setTransformRequest] = useState<{ transformType: DatasetTransformPlan["transformType"]; columns: string[] } | null>(null);
  const [transformLoading, setTransformLoading] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);

  async function refreshAnalysisWorkspace(nextUploadId: string, nextSheetName: string) {
    const [nextProfile, nextRoutes] = await Promise.all([
      fetchAnalysisProfile({ uploadId: nextUploadId, sheetName: nextSheetName }),
      fetchAnalysisRouteSuggestion({ uploadId: nextUploadId, sheetName: nextSheetName }),
    ]);
    setProfile(nextProfile);
    setRoutes(nextRoutes);
  }

  useEffect(() => {
    if (!upload || !selectedSheet) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchAnalysisProfile({ uploadId: upload.uploadId, sheetName: selectedSheet.sheetName }),
      fetchAnalysisRouteSuggestion({ uploadId: upload.uploadId, sheetName: selectedSheet.sheetName }),
    ])
      .then(([nextProfile, nextRoutes]) => {
        if (cancelled) return;
        setProfile(nextProfile);
        setRoutes(nextRoutes);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "分析工作台加载失败。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [upload?.uploadId, selectedSheet?.sheetName]);

  const routeCards = useMemo(() => {
    if (!routes) return [];
    const index = new Map<AnalysisType, RouteSuggestion["recommendedRoutes"][number]>();
    [...routes.recommendedRoutes, ...routes.blockedRoutes].forEach((item) => index.set(item.analysisType, item));
    return (["attribution", "forecast", "supervised_ml", "clustering"] as AnalysisType[]).map((id) => index.get(id)).filter(Boolean);
  }, [routes]);

  async function handlePreviewTransform(recommendation: DatasetRecommendation) {
    if (!upload || !selectedSheet) return;
    if (!isPreviewableTransform(recommendation.actionType)) return;
    setTransformLoading(true);
    setError(null);
    try {
      const plan = await planDatasetTransform({
        uploadId: upload.uploadId,
        sheetName: selectedSheet.sheetName,
        transformType: recommendation.actionType,
        columns: recommendation.columns,
      });
      setTransformPlan(plan);
      setTransformRequest({ transformType: recommendation.actionType, columns: recommendation.columns });
    } catch (err) {
      setError(err instanceof Error ? err.message : "预处理计划生成失败。");
    } finally {
      setTransformLoading(false);
    }
  }

  async function handleApplyTransform() {
    if (!upload || !selectedSheet || !transformRequest) return;
    setTransformLoading(true);
    setError(null);
    try {
      const result = await executeDatasetTransform({
        uploadId: upload.uploadId,
        sheetName: selectedSheet.sheetName,
        transformType: transformRequest.transformType,
        columns: transformRequest.columns,
        confirmed: true,
      });
      setUpload(result.upload);
      setSelectedSheet(result.sheet);
      await refreshAnalysisWorkspace(result.upload.uploadId, result.sheet.sheetName);
      setTransformPlan(null);
      setTransformRequest(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "预处理执行失败。");
    } finally {
      setTransformLoading(false);
    }
  }

  async function handleStartRoute(analysisType: AnalysisType) {
    if (!upload || !selectedSheet || !profile) return;
    if (analysisType === "forecast") {
      navigate("/forecast");
      return;
    }
    if (analysisType === "supervised_ml" || analysisType === "clustering") {
      navigate(`/analysis/workflows/${analysisType === "supervised_ml" ? "supervised-ml" : "clustering"}`, {
        state: {
          targetColumn: profile.targetCandidates[0] ?? null,
          featureColumns: [...profile.numericColumns, ...profile.categoricalColumns].slice(0, 12),
          clusterCount: analysisType === "clustering" ? 3 : null,
        },
      });
      return;
    }
    setStartingRoute(analysisType);
    setError(null);
    try {
      const request = {
        uploadId: upload.uploadId,
        sheetName: selectedSheet.sheetName,
        targetColumn: profile.targetCandidates[0] ?? null,
        timeColumn: profile.timeColumnCandidates[0] ?? null,
        groupingColumns: profile.groupingCandidates.slice(0, 3),
        featureColumns: [...profile.numericColumns, ...profile.categoricalColumns].slice(0, 12),
        clusterCount: null,
      };
      const detail = await startAttributionWorkflow(request);
      if (detail.nextPath) {
        navigate(detail.nextPath);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "工作流启动失败。");
    } finally {
      setStartingRoute(null);
    }
  }

  async function handleAgentTransformApplied(result: DatasetTransformResult) {
    setUpload(result.upload);
    setSelectedSheet(result.sheet);
    await refreshAnalysisWorkspace(result.upload.uploadId, result.sheet.sheetName);
  }

  function handleAgentOpenWorkflow(analysisType: AnalysisType) {
    if (!profile) return;
    if (analysisType === "forecast") {
      navigate("/forecast");
      return;
    }
    if (analysisType === "attribution") {
      void handleStartRoute("attribution");
      return;
    }
    navigate(`/analysis/workflows/${analysisType === "supervised_ml" ? "supervised-ml" : "clustering"}`, {
      state: {
        targetColumn: profile.targetCandidates[0] ?? null,
        featureColumns: [...profile.numericColumns, ...profile.categoricalColumns].slice(0, 12),
        clusterCount: analysisType === "clustering" ? 3 : null,
        openedByAgent: true,
      },
    });
  }

  if (!upload || !selectedSheet) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="分析工作台"
          title="Data Analysis Platform"
          description="上传成功后，这里会先做数据理解，再决定进入预测、归因、监督学习还是聚类。"
        />
        <div className="space-y-4">
          <EmptyState title="还没有可分析的数据" detail="先去上传文件，系统会带你进入分析工作台。" />
          <button type="button" className={controls.primaryButton} onClick={() => navigate("/upload")}>
            去上传数据
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="分析工作台"
        title="Data Analysis Platform"
        description={`${upload.fileName} / ${selectedSheet.sheetName} · 先看数据画像，再选 workflow；不再默认把所有数据都塞进预测流程。`}
        action={
          <div className="flex flex-wrap gap-2">
            <button type="button" className={controls.primaryButton} onClick={() => setAgentOpen(true)}>
              平台副驾驶
            </button>
            <button type="button" className={controls.secondaryButton} onClick={() => navigate("/upload")}>
              返回上传页
            </button>
            <button type="button" className={controls.secondaryButton} onClick={() => navigate("/forecast")}>
              直接去预测
            </button>
          </div>
        }
      />

      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label="正在构建数据画像与任务推荐..." /> : null}

      {profile ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <StatCard label="Readiness Score" value={`${profile.readinessScore.overall}`} hint={profile.readinessScore.summary} tone={analysisTone(profile.readinessScore.overall)} />
            <StatCard label="数据规模" value={`${profile.rowCountApprox ?? 0} 行`} hint={`${profile.columnCount} 列 / 预览 ${profile.previewRowCount} 行`} tone="info" />
            <StatCard label="时间列候选" value={profile.timeColumnCandidates[0] ?? "未识别"} hint={`${profile.timeColumnCandidates.length} 个候选`} />
            <StatCard label="目标列候选" value={profile.targetCandidates[0] ?? "未识别"} hint={`${profile.targetCandidates.length} 个候选`} tone="good" />
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
            <SectionCard title="Data Profiling Summary" description="这里是统一的数据画像输出，后续 UI 与 Agent 都会共用这份结构。">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                <div className={`${surface.softPanel} p-4`}>
                  <div className={`text-xs ${surface.mutedText}`}>字段类型分布</div>
                  <div className={`mt-3 text-sm leading-6 ${surface.strongText}`}>
                    {Object.entries(profile.typeCounts).map(([key, value]) => (
                      <div key={key}>{key}: {value}</div>
                    ))}
                  </div>
                </div>
                <div className={`${surface.softPanel} p-4`}>
                  <div className={`text-xs ${surface.mutedText}`}>候选列</div>
                  <div className={`mt-3 space-y-2 text-sm ${surface.strongText}`}>
                    <div>时间：{profile.timeColumnCandidates.join("、") || "-"}</div>
                    <div>目标：{profile.targetCandidates.join("、") || "-"}</div>
                    <div>分组：{profile.groupingCandidates.join("、") || "-"}</div>
                  </div>
                </div>
                <div className={`${surface.softPanel} p-4`}>
                  <div className={`text-xs ${surface.mutedText}`}>可用特征池</div>
                  <div className={`mt-3 space-y-2 text-sm ${surface.strongText}`}>
                    <div>数值：{profile.numericColumns.length}</div>
                    <div>类别：{profile.categoricalColumns.length}</div>
                    <div>文本：{profile.textColumns.length}</div>
                  </div>
                </div>
              </div>

              <div className="mt-5 space-y-3">
                {profile.readinessScore.dimensions.map((dimension) => (
                  <div key={dimension.key} className="analysis-card-rise rounded-2xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-[#0b1020]">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-900 dark:text-white">{dimension.label}</div>
                      <Badge tone={analysisTone(dimension.score)}>{dimension.score}</Badge>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                      <div
                        className="analysis-progress-fill h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700"
                        style={{ width: `${Math.max(dimension.score, 6)}%` }}
                      />
                    </div>
                    <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">{dimension.reason}</div>
                  </div>
                ))}
              </div>
            </SectionCard>

            <SectionCard title="问题清单" description="这些问题项同时服务手动流程和后续 Agent 解释。">
              <div className="space-y-3">
                {profile.issues.map((issue, index) => (
                  <div key={`${issue.issueType}:${index}`} className="rounded-2xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-[#151b2e]">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={issue.severity === "high" ? "bad" : issue.severity === "warn" ? "warn" : "info"}>{issue.issueType}</Badge>
                      {issue.columns.slice(0, 3).map((column) => <Badge key={`${issue.issueType}:${column}`} tone="neutral">{column}</Badge>)}
                    </div>
                    <div className="mt-2 font-medium text-slate-900 dark:text-white">{issue.title}</div>
                    <div className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{issue.description}</div>
                  </div>
                ))}
              </div>
            </SectionCard>
          </div>

          <SectionCard title="Task Router" description="第一版按 profile heuristics 推荐任务，不走黑盒判断。">
            <div className="grid gap-4 xl:grid-cols-2">
              {routeCards.map((route) => route ? (
                <div key={route.analysisType} className={`analysis-card-rise rounded-3xl border p-5 transition ${route.recommended ? "analysis-recommended-glow border-cyan-300 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-400/10" : "border-slate-200 bg-white dark:border-white/10 dark:bg-[#151b2e]"}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-lg font-semibold text-slate-950 dark:text-white">{route.label}</div>
                      <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">匹配度 {route.matchScore}%</div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {route.recommended ? <Badge tone="good">推荐</Badge> : null}
                      <Badge tone={route.eligible ? "info" : "warn"}>{route.eligible ? "可进入" : "需补充配置"}</Badge>
                    </div>
                  </div>
                  <div className="mt-4 space-y-2 text-sm text-slate-700 dark:text-slate-200">
                    {route.reasons.map((reason) => <div key={reason}>• {reason}</div>)}
                  </div>
                  <div className="analysis-progress-shell mt-4 h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                    <div
                      className="analysis-progress-fill h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700"
                      style={{ width: `${Math.max(route.matchScore, 5)}%` }}
                    />
                  </div>
                  {route.requiredInputs.length ? (
                    <div className="mt-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">所需补充</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {route.requiredInputs.map((item) => <Badge key={item} tone="warn">{item}</Badge>)}
                      </div>
                    </div>
                  ) : null}
                  {route.warnings.length ? (
                    <div className="mt-4 text-xs leading-5 text-amber-700 dark:text-amber-200">{route.warnings.join("；")}</div>
                  ) : null}
                  <div className="mt-5">
                    <button
                      type="button"
                      className={route.eligible ? controls.primaryButton : controls.secondaryButton}
                      disabled={startingRoute !== null && startingRoute !== route.analysisType}
                      onClick={() => void handleStartRoute(route.analysisType)}
                    >
                      {startingRoute === route.analysisType ? "进入中..." : `进入${routeLabels[route.analysisType]}`}
                    </button>
                  </div>
                </div>
              ) : null)}
            </div>
          </SectionCard>

          <SectionCard title="预处理建议" description="这几项改动都会先解释影响，再由你确认执行。">
            <div className="grid gap-4 xl:grid-cols-2">
              {profile.recommendations.map((recommendation) => (
                <div key={recommendation.recommendationId} className="analysis-card-rise rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="info">{recommendation.actionType}</Badge>
                    {recommendation.columns.slice(0, 3).map((column) => <Badge key={`${recommendation.recommendationId}:${column}`} tone="neutral">{column}</Badge>)}
                  </div>
                  <div className="mt-3 text-lg font-semibold text-slate-950 dark:text-white">{recommendation.title}</div>
                  <div className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{recommendation.description}</div>
                  <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">预期收益：{recommendation.expectedBenefit}</div>
                  {isPreviewableTransform(recommendation.actionType) ? (
                    <div className="mt-4">
                      <button type="button" className={controls.secondaryButton} disabled={transformLoading} onClick={() => void handlePreviewTransform(recommendation)}>
                        {transformLoading && transformRequest?.transformType === recommendation.actionType ? "分析中..." : "先看影响说明"}
                      </button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>

            {transformPlan ? (
              <div className="analysis-slide-expand mt-5 rounded-3xl border border-cyan-300 bg-cyan-50 p-5 dark:border-cyan-400/30 dark:bg-cyan-400/10">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-950 dark:text-white">Transform Preview</div>
                    <div className="mt-1 text-sm leading-6 text-slate-700 dark:text-slate-200">{transformPlan.explanation}</div>
                  </div>
                  <Badge tone="info">{transformPlan.transformType}</Badge>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className={`${surface.softPanel} p-4`}>
                    <div className={`text-xs ${surface.mutedText}`}>执行前</div>
                    <div className={`mt-2 text-2xl font-semibold ${surface.strongText}`}>{transformPlan.readinessBefore.overall}</div>
                  </div>
                  <div className={`${surface.softPanel} p-4`}>
                    <div className={`text-xs ${surface.mutedText}`}>执行后（预计）</div>
                    <div className={`mt-2 text-2xl font-semibold ${surface.strongText}`}>{transformPlan.readinessAfter.overall}</div>
                  </div>
                </div>
                <div className="analysis-compare-bar mt-4 h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                  <div
                    className="analysis-compare-fill h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400"
                    style={{ width: `${Math.max(transformPlan.readinessAfter.overall, 6)}%` }}
                  />
                </div>
                {transformPlan.expectedEffects.length ? (
                  <div className="mt-4 space-y-2 text-sm text-slate-700 dark:text-slate-200">
                    {transformPlan.expectedEffects.map((item) => <div key={item}>• {item}</div>)}
                  </div>
                ) : null}
                <div className="mt-5 flex flex-wrap gap-2">
                  <button type="button" className={controls.primaryButton} disabled={transformLoading} onClick={() => void handleApplyTransform()}>
                    {transformLoading ? "执行中..." : "确认执行这个变换"}
                  </button>
                  <button type="button" className={controls.secondaryButton} onClick={() => { setTransformPlan(null); setTransformRequest(null); }}>
                    取消
                  </button>
                </div>
              </div>
            ) : null}
          </SectionCard>
        </>
      ) : null}

      {upload && selectedSheet && profile ? (
        <AnalysisAgentDrawer
          open={agentOpen}
          onClose={() => setAgentOpen(false)}
          uploadId={upload.uploadId}
          sheetName={selectedSheet.sheetName}
          currentPage="/analysis"
          profile={profile}
          routes={routes}
          onDatasetTransformed={handleAgentTransformApplied}
          onOpenWorkflow={handleAgentOpenWorkflow}
        />
      ) : null}
    </div>
  );
}
