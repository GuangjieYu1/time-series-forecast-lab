import { Badge, SectionCard, surface } from "../../shared/components/Ui";
import type { DataHealth } from "../../shared/types/api";

function percentText(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function levelTone(level: DataHealth["level"]): "good" | "info" | "warn" | "bad" {
  if (level === "excellent") return "good";
  if (level === "good") return "info";
  if (level === "fair") return "warn";
  return "bad";
}

function levelText(level: DataHealth["level"]) {
  if (level === "excellent") return "优秀";
  if (level === "good") return "良好";
  if (level === "fair") return "一般";
  return "偏弱";
}

export function DataHealthPanel({ dataHealth }: { dataHealth: DataHealth | null | undefined }) {
  if (!dataHealth) {
    return (
      <SectionCard title="数据健康报告" description="当前实验还没有生成可用的数据健康报告。">
        <div className={`text-sm ${surface.mutedText}`}>请先完成一次预测运行，再查看数据质量、连续性和样本充分度分析。</div>
      </SectionCard>
    );
  }

  const { diagnostics } = dataHealth;
  const metricCards = [
    ["健康分", `${dataHealth.score}/100`],
    ["频率", diagnostics.frequency ?? "-"],
    ["有效样本", String(diagnostics.validPointCount)],
    ["训练 / 测试", `${diagnostics.trainPointCount} / ${diagnostics.testPointCount}`],
    ["连续性覆盖率", percentText(diagnostics.continuityCoverage)],
    ["时间跨度", diagnostics.timeSpanDays === null ? "-" : `${diagnostics.timeSpanDays} 天`],
  ];
  const diagnosticCards = [
    ["非法时间率", percentText(diagnostics.invalidTimeRate)],
    ["目标缺失率", percentText(diagnostics.targetMissingRate)],
    ["重复时间率", percentText(diagnostics.duplicateTimeRate)],
    ["异常值率", percentText(diagnostics.outlierRate)],
    ["样本丢弃率", percentText(diagnostics.droppedRowRate)],
    ["时间连续性", diagnostics.timeContinuous ? "连续" : "存在缺口"],
    ["训练集充分性", diagnostics.trainSizeSufficient ? "充足" : "偏短"],
    ["测试集合理性", diagnostics.testSizeReasonable ? "合理" : "需调整"],
  ];

  return (
    <SectionCard title="数据健康报告" description="预测前的数据质量、连续性和样本充分度摘要。">
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        {metricCards.map(([label, value]) => (
          <div key={label} className={`${surface.softPanel} p-4`}>
            <div className={`text-xs ${surface.mutedText}`}>{label}</div>
            <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Badge tone={levelTone(dataHealth.level)}>等级：{levelText(dataHealth.level)}</Badge>
        {diagnostics.timeStart ? <Badge tone="neutral">开始：{diagnostics.timeStart}</Badge> : null}
        {diagnostics.timeEnd ? <Badge tone="neutral">结束：{diagnostics.timeEnd}</Badge> : null}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-5">
          <div>
            <div className={`mb-3 text-sm font-semibold ${surface.strongText}`}>Warnings</div>
            <div className="space-y-2">
              {(dataHealth.warnings.length ? dataHealth.warnings : ["当前未检测到额外风险警告。"]).map((warning) => (
                <div key={warning} className="rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm text-amber-900 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
                  {warning}
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className={`mb-3 text-sm font-semibold ${surface.strongText}`}>Suggestions</div>
            <div className="space-y-2">
              {(dataHealth.suggestions.length ? dataHealth.suggestions : ["当前没有额外建议，可直接进入模型比较与残差分析。"]).map((suggestion) => (
                <div key={suggestion} className={`${surface.softPanel} px-4 py-3 text-sm ${surface.strongText}`}>
                  {suggestion}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div>
          <div className={`mb-3 text-sm font-semibold ${surface.strongText}`}>Diagnostics</div>
          <div className="grid gap-3 sm:grid-cols-2">
            {diagnosticCards.map(([label, value]) => (
              <div key={label} className={`${surface.softPanel} p-4`}>
                <div className={`text-xs ${surface.mutedText}`}>{label}</div>
                <div className={`mt-2 text-base font-semibold ${surface.strongText}`}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
