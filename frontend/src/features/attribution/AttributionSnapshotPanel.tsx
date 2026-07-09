import { Badge, SectionCard } from "../../shared/components/Ui";
import type { AttributionSnapshot, AttributionSnapshotSection } from "../../shared/types/api";

function highlightEntries(section: AttributionSnapshotSection) {
  return section.highlights.slice(0, 6);
}

function renderHighlightValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Math.abs(value) < 1 ? value.toFixed(4) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.join("、");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function SnapshotSectionCard({
  section,
  onAskAgent
}: {
  section: AttributionSnapshotSection;
  onAskAgent: (prompt: string) => void;
}) {
  return (
    <SectionCard
      title={section.title}
      description="这里是当前实验的归因证据摘要。你可以直接把任意追问交给右侧 Agent。"
      action={
        section.askAgentPrompts[0] ? (
          <button type="button" className="rounded-full border border-cyan-300 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:bg-cyan-50 dark:border-cyan-400/30 dark:text-cyan-200 dark:hover:bg-cyan-400/10" onClick={() => onAskAgent(section.askAgentPrompts[0])}>
            Ask Agent
          </button>
        ) : null
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
          <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
            <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Summary</div>
            <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700 dark:text-slate-200">
              {section.summary.length ? section.summary.map((item) => <div key={item}>• {item}</div>) : <div className="text-slate-500 dark:text-slate-400">暂无摘要。</div>}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
            <div className="text-xs uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Ask Agent</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {section.askAgentPrompts.length ? (
                section.askAgentPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => onAskAgent(prompt)}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700 dark:border-white/10 dark:bg-[#151b2e] dark:text-slate-200 dark:hover:border-cyan-400/30 dark:hover:text-cyan-200"
                  >
                    {prompt}
                  </button>
                ))
              ) : (
                <span className="text-xs text-slate-500 dark:text-slate-400">当前没有预设追问。</span>
              )}
            </div>
          </div>
        </div>

        {highlightEntries(section).length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {highlightEntries(section).map((item, index) => (
              <div key={`${section.title}:${index}`} className="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
                <div className="mb-3 flex flex-wrap gap-2">
                  <Badge tone="info">highlight #{index + 1}</Badge>
                </div>
                <div className="grid gap-2 text-sm">
                  {Object.entries(item).map(([key, value]) => (
                    <div key={key} className="grid gap-1 rounded-2xl border border-slate-200 bg-white px-3 py-2 dark:border-white/10 dark:bg-[#151b2e]">
                      <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">{key}</div>
                      <div className="text-sm text-slate-800 dark:text-slate-100">{renderHighlightValue(value)}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

export function AttributionSnapshotPanel({
  attribution,
  onAskAgent,
  heading = "Attribution Lab",
  description = "归因实验室把当前实验已有的 runtime、残差、特征解释和报告摘要整理成 5 个主区块。"
}: {
  attribution: AttributionSnapshot | null;
  onAskAgent: (prompt: string) => void;
  heading?: string;
  description?: string;
}) {
  if (!attribution) {
    return (
      <SectionCard title={heading} description={description}>
        <div className="rounded-3xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
          当前实验还没有可展示的归因快照，Agent 仍然可以基于 runtime / explainability / report 做 best-effort 分析。
        </div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-5">
      <SectionCard
        title={heading}
        description={description}
        action={
          attribution.updatedAt ? <Badge tone="info">更新于 {new Date(attribution.updatedAt).toLocaleString()}</Badge> : null
        }
      >
        <div className="space-y-3 text-sm leading-6 text-slate-700 dark:text-slate-200">
          <div>Attribution Lab 不把当前结果表述成严格因果证明，而是把已有实验输出整理成“解释证据 / 归因证据”。</div>
          {attribution.warnings.length ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
              {attribution.warnings.join("；")}
            </div>
          ) : null}
        </div>
      </SectionCard>

      <SnapshotSectionCard section={attribution.overview} onAskAgent={onAskAgent} />
      <SnapshotSectionCard section={attribution.quickDiagnosis} onAskAgent={onAskAgent} />
      <SnapshotSectionCard section={attribution.anomalyResidualLab} onAskAgent={onAskAgent} />
      <SnapshotSectionCard section={attribution.deepAttribution} onAskAgent={onAskAgent} />
      <SnapshotSectionCard section={attribution.scenarioExecutiveOutput} onAskAgent={onAskAgent} />
    </div>
  );
}
