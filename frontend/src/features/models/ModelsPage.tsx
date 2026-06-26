import { useEffect, useMemo, useState } from "react";
import { fetchDevice, fetchModels } from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import { zhCN } from "../../shared/i18n/zhCN";
import type { ModelCapability } from "../../shared/types/api";

const categoryOrder = ["Baseline", "Statistical", "Machine Learning", "Deep Learning", "Foundation Model"];
const categoryNames: Record<string, string> = {
  Baseline: "基线模型",
  Statistical: "统计模型",
  "Machine Learning": "机器学习",
  "Deep Learning": "深度学习",
  "Foundation Model": "基础模型"
};

function modelIcon(model: ModelCapability) {
  if (model.isFoundationModel) return "FM";
  if (model.modelFamily === "Deep Learning") return "DL";
  if (model.modelFamily === "Machine Learning") return "ML";
  if (model.category === "Statistical") return "ST";
  return "BL";
}

function statusTone(status: ModelCapability["installStatus"]) {
  if (status === "available") return "good";
  if (status === "downloading") return "info";
  if (status === "failed") return "bad";
  if (status === "planned") return "neutral";
  return "warn";
}

function statusText(status: ModelCapability["installStatus"]) {
  return {
    available: "可运行",
    not_installed: "未安装",
    downloading: "需要下载",
    planned: "计划中",
    failed: "不可用"
  }[status];
}

function capabilityBadges(model: ModelCapability) {
  return [
    { label: model.supportsPredictionInterval ? "支持区间" : "无区间", tone: model.supportsPredictionInterval ? "good" : "neutral" },
    { label: model.supportsMultipleTargets ? "多目标" : "单目标", tone: model.supportsMultipleTargets ? "good" : "neutral" },
    { label: model.supportsCovariates ? "协变量" : "无协变量", tone: model.supportsCovariates ? "info" : "neutral" },
    { label: model.requiresGpu ? "建议 GPU" : "CPU 可跑", tone: model.requiresGpu ? "warn" : "neutral" },
    { label: model.enabledInMvp ? "v0.2 可用" : "后续计划", tone: model.enabledInMvp ? "good" : "neutral" }
  ] as const;
}

export function ModelsPage() {
  const [models, setModels] = useState<ModelCapability[]>([]);
  const [device, setDevice] = useState("cpu");
  const [active, setActive] = useState("Baseline");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [modelList, detectedDevice] = await Promise.all([fetchModels(), fetchDevice()]);
        setModels(modelList);
        setDevice(detectedDevice);
        const firstCategory = categoryOrder.find((category) => modelList.some((model) => model.category === category));
        if (firstCategory) setActive(firstCategory);
      } catch (err) {
        setError(err instanceof Error ? err.message : "模型库加载失败。");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const categories = useMemo(() => categoryOrder.filter((category) => models.some((model) => model.category === category)), [models]);
  const shown = models.filter((model) => model.category === active);
  const available = models.filter((model) => model.installStatus === "available").length;
  const unavailable = models.filter((model) => model.installStatus === "not_installed" || model.installStatus === "failed").length;
  const planned = models.filter((model) => model.installStatus === "planned").length;
  const downloading = models.filter((model) => model.installStatus === "downloading").length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="模型库"
        title="模型能力、依赖状态与预测边界"
        description={`当前推理设备：${device}。模型库只负责声明能力与可用性，单个模型不可用不会阻断其他模型运行。`}
        action={<Badge tone={downloading ? "warn" : "good"}>{downloading ? `${downloading} 个模型待下载` : "依赖状态已同步"}</Badge>}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="可运行模型" value={available} hint="已通过后端依赖检测" tone="good" />
        <StatCard label="需安装/失败" value={unavailable} hint="会在实验中自动隔离" tone={unavailable ? "warn" : "neutral"} />
        <StatCard label="计划模型" value={planned} hint="展示路线图，不参与 v0.2 运行" />
        <StatCard label="当前设备" value={device.toUpperCase()} hint="CUDA / MPS / CPU 自动检测" tone="info" />
      </div>

      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label="正在加载模型注册表..." /> : null}
      {!loading && !models.length ? <EmptyState title="后端没有返回模型" detail="请确认 FastAPI 服务已启动，并检查 /api/models。" /> : null}

      {models.length ? (
        <div className="grid gap-5 xl:grid-cols-[240px_1fr]">
          <SectionCard title="模型分层" description="按业务解释性和建模复杂度分组。">
            <div className="space-y-2">
              {categories.map((category) => {
                const count = models.filter((model) => model.category === category).length;
                return (
                  <button
                    key={category}
                    className={`w-full justify-between ${active === category ? controls.primaryButton : controls.secondaryButton}`}
                    onClick={() => setActive(category)}
                    type="button"
                  >
                    <span>{categoryNames[category] ?? category}</span>
                    <span className="text-xs opacity-75">{count}</span>
                  </button>
                );
              })}
            </div>
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-2">
            {shown.map((model) => (
              <article key={model.id} className={`${surface.panel} overflow-hidden p-5`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-slate-950 text-sm font-semibold text-white shadow-lg shadow-indigo-500/10 dark:bg-white dark:text-slate-950">
                      {modelIcon(model)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className={`text-lg font-semibold ${surface.strongText}`}>{model.name}</h3>
                        <Badge>{model.modelFamily || model.category}</Badge>
                      </div>
                      <p className={`mt-2 text-sm leading-6 ${surface.mutedText}`}>
                        {zhCN.modelDescriptions[model.id as keyof typeof zhCN.modelDescriptions] ?? model.shortDescription}
                      </p>
                    </div>
                  </div>
                  <Badge tone={statusTone(model.installStatus)}>{statusText(model.installStatus)}</Badge>
                </div>

                <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div className={`${surface.softPanel} p-3`}>
                    <div className={surface.mutedText}>预测步长</div>
                    <div className={`mt-1 font-semibold ${surface.strongText}`}>{model.minHorizon} - {model.maxHorizon}</div>
                  </div>
                  <div className={`${surface.softPanel} p-3`}>
                    <div className={surface.mutedText}>运行优先级</div>
                    <div className={`mt-1 font-semibold ${surface.strongText}`}>{model.priority}</div>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  {capabilityBadges(model).map((badge) => (
                    <Badge key={badge.label} tone={badge.tone}>{badge.label}</Badge>
                  ))}
                </div>

                {model.unavailableReason ? (
                  <p className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
                    {model.unavailableReason}
                  </p>
                ) : null}

                {model.installCommand ? (
                  <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-300">
                    <div className="mb-1 font-medium text-slate-500 dark:text-slate-400">安装命令</div>
                    <code className="break-all">{model.installCommand}</code>
                  </div>
                ) : null}

                {(model.paperUrl ?? model.representativePaperUrl) ? (
                  <a
                    className="mt-4 inline-flex text-sm font-semibold text-indigo-600 hover:underline dark:text-indigo-300"
                    href={model.paperUrl ?? model.representativePaperUrl ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    代表论文：{model.paperTitle ?? model.representativePaperTitle ?? "查看论文"}
                  </a>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
