import { useMemo, useState } from "react";
import { analyzeWorkbenchIdea } from "../../shared/api/client";
import { ErrorBanner } from "../../shared/components/Status";
import { Badge, controls, SectionCard } from "../../shared/components/Ui";
import type { WorkbenchIdeaAnalyzeResponse } from "../../shared/types/api";

export function WorkbenchIdeaPanel({
  disabled,
  targetColumn,
  frequency,
  availableColumns,
  horizon,
  domain = null
}: {
  disabled: boolean;
  targetColumn: string | null;
  frequency: string | null;
  availableColumns: string[];
  horizon: number;
  domain?: string | null;
}) {
  const [idea, setIdea] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WorkbenchIdeaAnalyzeResponse | null>(null);

  const disabledReason = useMemo(() => {
    if (disabled) return "需要先上传并选择实验数据。";
    if (!targetColumn) return "请先至少选择一个目标列。";
    return null;
  }, [disabled, targetColumn]);

  async function handleAnalyze() {
    if (!idea.trim() || disabledReason) return;
    setLoading(true);
    setError(null);
    try {
      setResult(
        await analyzeWorkbenchIdea({
          idea: idea.trim(),
          context: {
            targetColumn,
            frequency,
            availableColumns,
            horizon,
            domain
          },
          mode: "offline"
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "想法分析失败。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <SectionCard
      title="我有一个想法"
      description="例如：我想分析航线收入下降的原因。Workbench Agent 会先给出 route、所需输入、协变量方案和泄漏风险提醒。"
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-3">
          <textarea
            className={`${controls.input} min-h-[112px]`}
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            placeholder="例如：我想分析航线收入下降的原因"
            disabled={Boolean(disabledReason) || loading}
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className={controls.primaryButton}
              onClick={() => void handleAnalyze()}
              disabled={!idea.trim() || Boolean(disabledReason) || loading}
            >
              {loading ? "分析中..." : "分析想法"}
            </button>
            {disabledReason ? <span className="text-xs text-slate-500 dark:text-slate-400">{disabledReason}</span> : null}
          </div>
          <ErrorBanner message={error} />
        </div>

        <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
          {result ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="info">route {result.route}</Badge>
                <Badge tone={result.confidence >= 0.75 ? "good" : result.confidence >= 0.5 ? "warn" : "neutral"}>
                  confidence {Math.round(result.confidence * 100)}%
                </Badge>
              </div>
              <div className="text-sm leading-6 text-slate-700 dark:text-slate-200">{result.rationale}</div>

              <WorkbenchList title="requiredInputs" items={result.requiredInputs} />
              <WorkbenchList title="candidateDataSources" items={result.candidateDataSources.map((item) => `${item.name} · ${item.futureAvailability}`)} />
              <WorkbenchList title="nextApiCalls" items={result.nextApiCalls} />

              {result.covariatePlan ? (
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-[#151b2e]">
                  <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">covariatePlan</div>
                  <div className="mt-2 text-slate-800 dark:text-slate-100">
                    类型：{result.covariatePlan.covariateType}
                    <br />
                    Backtest：{result.covariatePlan.backtestPolicy || "-"}
                    <br />
                    Forecast：{result.covariatePlan.forecastPolicy || "-"}
                  </div>
                </div>
              ) : null}

              {result.leakageWarnings.length ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                  {result.leakageWarnings.join("；")}
                </div>
              ) : null}

              {result.covariatePlan?.covariateType === "unknown_future" || result.candidateDataSources.some((item) => item.futureAvailability === "unknown_future") ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                  当前 v0.4 实验配置页只支持 known_future / static。这里如果涉及未来未知数据，只作为 advisory 提示，不会直接下发到 forecast 主流程。
                </div>
              ) : null}
            </div>
          ) : (
            <div className="flex min-h-[180px] items-center justify-center text-center text-sm leading-6 text-slate-500 dark:text-slate-400">
              这里会显示 route、confidence、所需输入、候选数据源、协变量方案与泄漏提醒。
            </div>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function WorkbenchList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-[#151b2e]">
      <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">{title}</div>
      <div className="mt-2 space-y-1 text-slate-700 dark:text-slate-200">
        {items.length ? items.map((item) => <div key={item}>• {item}</div>) : <div className="text-slate-500 dark:text-slate-400">-</div>}
      </div>
    </div>
  );
}
