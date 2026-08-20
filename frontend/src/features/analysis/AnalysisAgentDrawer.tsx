import { useEffect, useMemo, useState } from "react";
import {
  analyzeWithPlatformAgent,
  executeDatasetTransform,
  planDatasetTransform,
} from "../../shared/api/client";
import { ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, SectionCard, SideDrawer, surface } from "../../shared/components/Ui";
import type {
  AgentDecisionCard,
  AnalysisAgentResponse,
  AnalysisType,
  DatasetProfile,
  DatasetTransformPlan,
  DatasetTransformResult,
  DatasetTransformType,
  RouteSuggestion,
} from "../../shared/types/api";

const transformActionIds: DatasetTransformType[] = [
  "drop_constant_columns",
  "drop_high_missing_columns",
  "drop_identifier_columns",
  "normalize_numeric_features",
];

const quickPrompts = [
  "这份数据适合做什么？",
  "有没有应该先删除的常量列或标识列？",
  "如果我要做监督学习，先处理哪些列最划算？",
  "如果我要做聚类，先帮我判断特征是否需要标准化。",
];

function isTransformAction(actionId: string): actionId is DatasetTransformType {
  return transformActionIds.includes(actionId as DatasetTransformType);
}

function routeLabel(analysisType: AnalysisType) {
  return {
    attribution: "归因分析",
    clustering: "聚类分析",
    forecast: "时间序列预测",
    supervised_ml: "监督学习",
  }[analysisType];
}

function readinessTone(score: number): "good" | "info" | "warn" | "bad" {
  if (score >= 80) return "good";
  if (score >= 65) return "info";
  if (score >= 50) return "warn";
  return "bad";
}

function summarizeIssueDelta(result: DatasetTransformResult) {
  return {
    before: result.beforeIssues.length,
    after: result.afterIssues.length,
    delta: result.afterIssues.length - result.beforeIssues.length,
  };
}

function compareReadiness(before: DatasetProfile["readinessScore"], after: DatasetProfile["readinessScore"]) {
  return before.dimensions.map((dimension) => {
    const next = after.dimensions.find((item) => item.key === dimension.key);
    const nextScore = next?.score ?? dimension.score;
    return {
      key: dimension.key,
      label: dimension.label,
      before: dimension.score,
      after: nextScore,
      delta: nextScore - dimension.score,
    };
  });
}

function datasetDelta(beforeProfile: DatasetProfile, result: DatasetTransformResult) {
  const beforeColumns = beforeProfile.columns.map((column) => column.name);
  const afterColumns = result.datasetProfile.columns.map((column) => column.name);
  const removedColumns = beforeColumns.filter((column) => !afterColumns.includes(column));
  const retainedColumns = afterColumns.filter((column) => beforeColumns.includes(column));
  return {
    beforeCount: beforeColumns.length,
    afterCount: afterColumns.length,
    removedColumns,
    retainedColumns,
  };
}

export function AnalysisAgentDrawer({
  open,
  onClose,
  uploadId,
  sheetName,
  currentPage,
  profile,
  routes,
  onDatasetTransformed,
  onOpenWorkflow,
}: {
  open: boolean;
  onClose: () => void;
  uploadId: string;
  sheetName: string;
  currentPage: string;
  profile: DatasetProfile;
  routes: RouteSuggestion | null;
  onDatasetTransformed: (result: DatasetTransformResult) => void | Promise<void>;
  onOpenWorkflow: (analysisType: AnalysisType) => void;
}) {
  const [prompt, setPrompt] = useState(quickPrompts[0]);
  const [response, setResponse] = useState<AnalysisAgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewingCardId, setPreviewingCardId] = useState<string | null>(null);
  const [executingCardId, setExecutingCardId] = useState<string | null>(null);
  const [planByCardId, setPlanByCardId] = useState<Record<string, DatasetTransformPlan>>({});
  const [resultByCardId, setResultByCardId] = useState<Record<string, DatasetTransformResult>>({});

  useEffect(() => {
    setResponse(null);
    setError(null);
    setPlanByCardId({});
    setResultByCardId({});
  }, [uploadId, sheetName]);

  const readinessSummary = useMemo(
    () => `${profile.readinessScore.overall}/100 · ${profile.readinessScore.summary}`,
    [profile.readinessScore.overall, profile.readinessScore.summary]
  );

  async function handleAnalyze(nextPrompt = prompt) {
    setLoading(true);
    setError(null);
    try {
      const nextResponse = await analyzeWithPlatformAgent({
        uploadId,
        sheetName,
        prompt: nextPrompt,
        currentPage,
      });
      setResponse(nextResponse);
      setPrompt(nextPrompt);
    } catch (err) {
      setError(err instanceof Error ? err.message : "平台副驾驶暂时无法分析这份数据。");
    } finally {
      setLoading(false);
    }
  }

  async function handlePreviewCard(card: AgentDecisionCard) {
    if (!isTransformAction(card.actionId)) return;
    setPreviewingCardId(card.cardId);
    setError(null);
    try {
      const preview = await planDatasetTransform({
        uploadId,
        sheetName,
        transformType: card.actionId,
        columns: card.columns,
      });
      setPlanByCardId((current) => ({ ...current, [card.cardId]: preview }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "暂时无法生成这张解释卡的前后对比。");
    } finally {
      setPreviewingCardId(null);
    }
  }

  async function handleExecuteCard(card: AgentDecisionCard) {
    if (card.actionType === "workflow") {
      onOpenWorkflow(card.actionId as AnalysisType);
      return;
    }
    if (!isTransformAction(card.actionId)) return;
    setExecutingCardId(card.cardId);
    setError(null);
    try {
      const result = await executeDatasetTransform({
        uploadId,
        sheetName,
        transformType: card.actionId,
        columns: card.columns,
        confirmed: true,
      });
      setResultByCardId((current) => ({ ...current, [card.cardId]: result }));
      await onDatasetTransformed(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "执行这张解释卡失败。");
    } finally {
      setExecutingCardId(null);
    }
  }

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title="平台副驾驶"
      description="先解释为什么建议这么做，再等待你确认执行；执行后会直接展示前后变化。"
      widthClassName="w-full max-w-[960px]"
    >
      <div className="space-y-5">
        <ErrorBanner message={error} />

        <SectionCard title="当前上下文" description="这份上下文会作为 Agent 解释、推荐和确认执行的依据。">
          <div className="grid gap-3 md:grid-cols-2">
            <div className={`${surface.softPanel} p-4`}>
              <div className={`text-xs ${surface.mutedText}`}>数据画像</div>
              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>{readinessSummary}</div>
            </div>
            <div className={`${surface.softPanel} p-4`}>
              <div className={`text-xs ${surface.mutedText}`}>推荐任务</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {(routes?.recommendedRoutes ?? []).slice(0, 3).map((route) => (
                  <Badge key={route.analysisType} tone={route.recommended ? "good" : "info"}>
                    {route.label} {route.matchScore}%
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="问平台副驾驶" description="你可以问“这份数据适合做什么”“为什么删这列”“聚类前要不要先标准化”等。">
          <div className="space-y-3">
            <textarea
              className={`${controls.input} min-h-[120px] border-slate-200 bg-white text-slate-950 dark:border-white/10 dark:bg-[#111827] dark:text-white`}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="例如：这份数据适合做什么？"
            />
            <div className="flex flex-wrap gap-2">
              {quickPrompts.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={controls.secondaryButton}
                  onClick={() => {
                    setPrompt(item);
                    void handleAnalyze(item);
                  }}
                  disabled={loading}
                >
                  {item}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={controls.primaryButton} onClick={() => void handleAnalyze()} disabled={loading}>
                {loading ? "分析中..." : "生成解释卡"}
              </button>
              <button
                type="button"
                className={controls.secondaryButton}
                onClick={() => {
                  setResponse(null);
                  setPlanByCardId({});
                  setResultByCardId({});
                }}
              >
                清空当前轮次
              </button>
            </div>
          </div>
        </SectionCard>

        {response ? (
          <>
            <SectionCard title="本轮解释与计划" description={response.message}>
              <div className="rounded-3xl border border-cyan-200 bg-cyan-50 p-4 text-sm leading-6 text-cyan-900 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100">
                {response.summary}
              </div>
              <div className="mt-4 space-y-3">
                {response.plan.map((step, index) => (
                  <div
                    key={step.stepId}
                    className="analysis-card-rise rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]"
                    style={{ animationDelay: `${index * 90}ms` }}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="font-semibold text-slate-950 dark:text-white">{step.title}</div>
                      <Badge tone={step.status === "completed" ? "good" : step.status === "running" ? "info" : "neutral"}>
                        <span className={step.status === "running" ? "analysis-live-dot" : ""}>{step.status}</span>
                      </Badge>
                    </div>
                    <div className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{step.description}</div>
                  </div>
                ))}
              </div>
              {response.warnings.length ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {response.warnings.map((warning) => <Badge key={warning} tone="warn">{warning}</Badge>)}
                </div>
              ) : null}
            </SectionCard>

            <SectionCard title="解释卡" description="变换类动作会先展示预计收益，再由你确认执行；执行后立刻展示前后对比。">
              <div className="space-y-4">
                {response.decisionCards.map((card, index) => {
                  const preview = planByCardId[card.cardId];
                  const result = resultByCardId[card.cardId];
                  const issueDelta = result ? summarizeIssueDelta(result) : null;
                  const previewDiff = preview ? compareReadiness(preview.readinessBefore, preview.readinessAfter) : [];
                  const resultDiff = result ? compareReadiness(result.readinessBefore, result.readinessAfter) : [];
                  const shapeDelta = result ? datasetDelta(profile, result) : null;
                  const transformNeedsPreview = card.actionType === "transform" && card.requiresConfirmation && !preview;
                  return (
                    <div
                      key={card.cardId}
                      className="analysis-card-rise rounded-3xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-[#151b2e]"
                      style={{ animationDelay: `${index * 110}ms` }}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={card.actionType === "transform" ? "info" : card.actionType === "workflow" ? "good" : "neutral"}>
                              {card.actionType}
                            </Badge>
                            {card.columns.slice(0, 4).map((column) => <Badge key={`${card.cardId}:${column}`} tone="neutral">{column}</Badge>)}
                          </div>
                          <div className="mt-3 text-lg font-semibold text-slate-950 dark:text-white">{card.title}</div>
                          <div className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{card.explanation}</div>
                          <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">预期收益：{card.expectedBenefit}</div>
                          <div className="mt-4 grid gap-3 md:grid-cols-2">
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>发现了什么</div>
                              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>{card.whatDetected || card.explanation}</div>
                            </div>
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>为什么建议这么做</div>
                              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>{card.whyRecommended || card.expectedBenefit}</div>
                            </div>
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>如果先不做</div>
                              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>{card.ifSkipped || "后续 workflow 会继续带着当前数据问题往下走。"}</div>
                            </div>
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>执行后预计改善</div>
                              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>{card.expectedChange || card.expectedBenefit}</div>
                            </div>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {card.actionType === "transform" ? (
                            <button
                              type="button"
                              className={controls.secondaryButton}
                              onClick={() => void handlePreviewCard(card)}
                              disabled={previewingCardId === card.cardId}
                            >
                              {previewingCardId === card.cardId ? "对比生成中..." : "先看前后对比"}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className={card.actionType === "workflow" ? controls.primaryButton : controls.primaryButton}
                            onClick={() => void handleExecuteCard(card)}
                            disabled={executingCardId === card.cardId || transformNeedsPreview}
                          >
                            {executingCardId === card.cardId
                              ? "执行中..."
                              : card.actionType === "workflow"
                                ? `打开${routeLabel(card.actionId as AnalysisType)}`
                                : transformNeedsPreview
                                  ? "先看前后对比"
                                  : card.requiresConfirmation
                                    ? "确认执行"
                                    : "执行"}
                          </button>
                        </div>
                      </div>

                      <div className="mt-4 flex flex-wrap gap-2">
                        <Badge tone={result ? "good" : preview ? "info" : "neutral"}>
                          {result ? "已执行完成" : preview ? "已生成预览，等待确认" : "先解释，后确认"}
                        </Badge>
                        {card.requiresConfirmation ? <Badge tone="warn">需要确认执行</Badge> : <Badge tone="neutral">只读 / 打开 workflow</Badge>}
                      </div>

                      {preview ? (
                        <div className="analysis-slide-expand mt-5 rounded-3xl border border-cyan-200 bg-cyan-50 p-4 dark:border-cyan-400/20 dark:bg-cyan-400/10">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="text-sm font-semibold text-slate-950 dark:text-white">执行前后预测</div>
                            <Badge tone="info">
                              {preview.readinessBefore.overall} → {preview.readinessAfter.overall}
                            </Badge>
                          </div>
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>执行前</div>
                              <div className={`mt-2 text-2xl font-semibold ${surface.strongText}`}>{preview.readinessBefore.overall}</div>
                            </div>
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>执行后（预计）</div>
                              <div className={`mt-2 text-2xl font-semibold ${surface.strongText}`}>{preview.readinessAfter.overall}</div>
                            </div>
                          </div>
                          <div className="analysis-compare-bar mt-4 h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                            <div
                              className="analysis-compare-fill h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400"
                              style={{ width: `${Math.max(preview.readinessAfter.overall, 6)}%` }}
                            />
                          </div>
                          <div className="mt-4 grid gap-3 md:grid-cols-2">
                            {previewDiff.map((dimension) => (
                              <div key={`${card.cardId}:${dimension.key}`} className={`${surface.softPanel} p-3`}>
                                <div className="flex items-center justify-between gap-3">
                                  <div className={`text-xs ${surface.mutedText}`}>{dimension.label}</div>
                                  <Badge tone={dimension.delta >= 0 ? "good" : "warn"}>
                                    {dimension.before} → {dimension.after}
                                  </Badge>
                                </div>
                                <div className="analysis-progress-shell mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                                  <div
                                    className="analysis-progress-fill h-full rounded-full"
                                    style={{ width: `${Math.max(dimension.after, 5)}%` }}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                          <div className="mt-3 space-y-2 text-sm text-slate-700 dark:text-slate-200">
                            {preview.expectedEffects.map((item) => <div key={item}>• {item}</div>)}
                          </div>
                        </div>
                      ) : null}

                      {result ? (
                        <div className="analysis-slide-expand mt-5 rounded-3xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-400/20 dark:bg-emerald-400/10">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="text-sm font-semibold text-slate-950 dark:text-white">执行完成 · 前后对比</div>
                            <Badge tone={readinessTone(result.readinessAfter.overall)}>
                              {result.readinessBefore.overall} → {result.readinessAfter.overall}
                            </Badge>
                          </div>
                          <div className="mt-3 grid gap-3 md:grid-cols-3">
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>Readiness</div>
                              <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>{result.qualityDeltaSummary}</div>
                            </div>
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>应用列</div>
                              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>{result.appliedColumns.join("、") || "-"}</div>
                            </div>
                            <div className={`${surface.softPanel} p-4`}>
                              <div className={`text-xs ${surface.mutedText}`}>问题变化</div>
                              <div className={`mt-2 text-sm leading-6 ${surface.strongText}`}>
                                {issueDelta ? `${issueDelta.before} → ${issueDelta.after}（${issueDelta.delta}）` : "-"}
                              </div>
                            </div>
                          </div>
                          {shapeDelta ? (
                            <div className="mt-4 grid gap-3 md:grid-cols-3">
                              <div className={`${surface.softPanel} p-4`}>
                                <div className={`text-xs ${surface.mutedText}`}>字段数变化</div>
                                <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>{shapeDelta.beforeCount} → {shapeDelta.afterCount}</div>
                              </div>
                              <div className={`${surface.softPanel} p-4 md:col-span-2`}>
                                <div className={`text-xs ${surface.mutedText}`}>移除字段</div>
                                <div className="mt-2 flex flex-wrap gap-2">
                                  {shapeDelta.removedColumns.length
                                    ? shapeDelta.removedColumns.map((column) => <Badge key={`${card.cardId}:removed:${column}`} tone="warn">{column}</Badge>)
                                    : <span className={`text-sm ${surface.strongText}`}>本次没有移除字段。</span>}
                                </div>
                              </div>
                            </div>
                          ) : null}
                          <div className="mt-4 grid gap-3 md:grid-cols-2">
                            {resultDiff.map((dimension) => (
                              <div key={`${card.cardId}:result:${dimension.key}`} className={`${surface.softPanel} p-3`}>
                                <div className="flex items-center justify-between gap-3">
                                  <div className={`text-xs ${surface.mutedText}`}>{dimension.label}</div>
                                  <Badge tone={dimension.delta >= 0 ? "good" : "warn"}>
                                    {dimension.before} → {dimension.after}
                                  </Badge>
                                </div>
                                <div className="analysis-progress-shell mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                                  <div
                                    className="analysis-progress-fill h-full rounded-full"
                                    style={{ width: `${Math.max(dimension.after, 5)}%` }}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                          <div className="mt-4 text-sm leading-6 text-slate-700 dark:text-slate-200">
                            新数据快照已生成：<span className="font-semibold">{result.upload.fileName}</span>，分析工作台已经切到了这份更新后的数据，方便你立刻继续复跑或切 workflow。
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </SectionCard>
          </>
        ) : null}
      </div>
    </SideDrawer>
  );
}
