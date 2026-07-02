import { Badge, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import { DeepSeekSettingsPanel } from "./DeepSeekSettingsPanel";
import { LocalMaintenancePanel } from "./LocalMaintenancePanel";

export function ApiSettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="API 设置"
        title="DeepSeek 报告与本地维护"
        description="这里既能配置 DeepSeek 中文报告，也能在本机环境下一键重建并重启本地服务。核心预测、模型比较、残差分析和历史回放不依赖 DeepSeek API。"
        action={<Badge tone="info">本地浏览器配置</Badge>}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="配置范围" value="本机" hint="API Key 仅保存在当前浏览器" tone="info" />
        <StatCard label="数据库策略" value="不落库" hint="不会写入 SQLite 实验历史" tone="good" />
        <StatCard label="报告模型" value="DeepSeek" hint="默认 deepseek-v4-flash" />
        <StatCard label="本地维护" value="一键重启" hint="API 设置页可触发本机重建" tone="warn" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <DeepSeekSettingsPanel />
          <LocalMaintenancePanel />
        </div>
        <SectionCard title="报告生成流程" description="生成时后端只读取实验结果摘要，不读取原始上传文件。">
          <div className="space-y-3">
            {["读取模型排行榜", "分析自动优化策略与逐轮结果", "分析残差与误差分布", "整理最终预测区间", "生成中文业务建议"].map((step, index) => (
              <div key={step} className={`${surface.softPanel} flex items-center gap-3 p-3`}>
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-semibold text-white dark:bg-indigo-400 dark:text-slate-950">
                  {index + 1}
                </span>
                <span className={`text-sm font-medium ${surface.strongText}`}>{step}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-2xl border border-cyan-200 bg-cyan-50 p-4 text-sm leading-6 text-cyan-800 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100">
            没有配置 API Key 时，报告面板会显示可操作提示；预测实验本身仍可完整运行。本地一键重建只在 localhost 场景开放，避免误触远端环境。
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
