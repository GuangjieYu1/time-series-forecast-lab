import { useEffect, useMemo, useState } from "react";
import { fetchDevice, fetchModels } from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface, Tabs } from "../../shared/components/Ui";
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

type ModelView = "cards" | "timeline" | "tree";

const modelHistory: Record<string, { year: number; lineage: string; milestone: string }> = {
  moving_average: { year: 1900, lineage: "Baseline", milestone: "早期平滑思想，适合做低方差基准。" },
  ets: { year: 1957, lineage: "Statistical", milestone: "指数平滑体系成形，面向趋势和季节性。" },
  naive: { year: 1960, lineage: "Baseline", milestone: "最小可用基线：未来等于最近观测。" },
  seasonal_naive: { year: 1960, lineage: "Baseline", milestone: "季节性基线：复用上一周期同位置。" },
  arima: { year: 1970, lineage: "Statistical", milestone: "Box-Jenkins 统计建模框架代表。" },
  random_forest: { year: 2001, lineage: "Machine Learning", milestone: "集成树模型，用滞后和滚动特征预测。" },
  xgboost: { year: 2016, lineage: "Machine Learning", milestone: "高性能 GBDT，适合结构化特征预测。" },
  prophet: { year: 2017, lineage: "Statistical", milestone: "可解释趋势、季节性和节假日建模。" },
  lightgbm: { year: 2017, lineage: "Machine Learning", milestone: "更高效的 GBDT，适合大样本特征工程。" },
  nbeats: { year: 2019, lineage: "Deep Learning", milestone: "神经基展开模型，强调可解释分解。" },
  nhits: { year: 2022, lineage: "Deep Learning", milestone: "层级插值结构，面向长预测步长。" },
  patchtst: { year: 2023, lineage: "Deep Learning", milestone: "Patch 化 Transformer，面向长序列预测。" },
  lag_llama: { year: 2023, lineage: "Foundation Model", milestone: "概率预测基础模型路线。" },
  timesfm: { year: 2023, lineage: "Foundation Model", milestone: "Google 时序基础模型，强调 zero-shot。" },
  moirai: { year: 2024, lineage: "Foundation Model", milestone: "统一训练的通用时序 Transformer。" },
  chronos: { year: 2024, lineage: "Foundation Model", milestone: "把时序 token 化并接入语言模型范式。" }
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

function historyFor(model: ModelCapability) {
  return modelHistory[model.id] ?? { year: 2026, lineage: model.modelFamily || model.category, milestone: "已纳入当前模型路线图。" };
}

function ModelCardArticle({ model }: { model: ModelCapability }) {
  return (
    <article className={`${surface.panel} overflow-hidden p-5`}>
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
  );
}

function TimelineView({ models }: { models: ModelCapability[] }) {
  const sortedModels = [...models].sort((left, right) => historyFor(left).year - historyFor(right).year || left.priority - right.priority);
  return (
    <SectionCard title="模型时间线" description="横向查看时间序列预测模型从平滑、统计、机器学习到基础模型的演进。">
      <div className="overflow-x-auto pb-2">
        <div className="relative flex min-w-[980px] gap-4 py-6">
          <div className="absolute left-4 right-4 top-[54px] h-px bg-gradient-to-r from-slate-200 via-indigo-300 to-cyan-300 dark:from-white/10 dark:via-indigo-300/30 dark:to-cyan-300/30" />
          {sortedModels.map((model) => {
            const history = historyFor(model);
            return (
              <article key={model.id} className="relative z-10 w-56 shrink-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-[#111827]">
                <div className="flex items-center justify-between">
                  <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white dark:bg-white dark:text-slate-950">{history.year}</span>
                  <Badge tone={statusTone(model.installStatus)}>{statusText(model.installStatus)}</Badge>
                </div>
                <div className="mt-5 flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-xs font-semibold text-indigo-700 dark:bg-indigo-400/10 dark:text-indigo-200">
                  {modelIcon(model)}
                </div>
                <h3 className={`mt-3 text-base font-semibold ${surface.strongText}`}>{model.name}</h3>
                <div className={`mt-1 text-xs ${surface.mutedText}`}>{categoryNames[history.lineage] ?? history.lineage}</div>
                <p className={`mt-3 text-xs leading-5 ${surface.mutedText}`}>{history.milestone}</p>
              </article>
            );
          })}
        </div>
      </div>
    </SectionCard>
  );
}

function TechTreeView({ models }: { models: ModelCapability[] }) {
  return (
    <SectionCard title="模型科技树" description="竖向查看从基线、统计模型到机器学习、深度学习、基础模型的能力路线。">
      <div className="grid gap-4 xl:grid-cols-5">
        {categoryOrder.map((category) => {
          const group = models
            .filter((model) => (historyFor(model).lineage || model.category) === category || model.category === category)
            .sort((left, right) => historyFor(left).year - historyFor(right).year || left.priority - right.priority);
          if (!group.length) return null;
          return (
            <div key={category} className="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-[#0b1020]">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <div className={`text-sm font-semibold ${surface.strongText}`}>{categoryNames[category] ?? category}</div>
                  <div className={`text-xs ${surface.mutedText}`}>{group.length} 个节点</div>
                </div>
                <Badge>{category}</Badge>
              </div>
              <div className="relative space-y-3 border-l border-slate-300 pl-4 dark:border-white/15">
                {group.map((model) => {
                  const history = historyFor(model);
                  return (
                    <article key={model.id} className="relative rounded-2xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-[#111827]">
                      <span className="absolute -left-[21px] top-5 h-3 w-3 rounded-full border-2 border-white bg-indigo-500 dark:border-[#0b1020]" />
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="text-xs font-semibold text-indigo-600 dark:text-indigo-300">{history.year}</div>
                          <h3 className={`mt-1 text-sm font-semibold ${surface.strongText}`}>{model.name}</h3>
                        </div>
                        <Badge tone={statusTone(model.installStatus)}>{statusText(model.installStatus)}</Badge>
                      </div>
                      <p className={`mt-2 text-xs leading-5 ${surface.mutedText}`}>{history.milestone}</p>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        <Badge tone={model.enabledInMvp ? "good" : "neutral"}>{model.enabledInMvp ? "可运行" : "计划中"}</Badge>
                        <Badge tone={model.requiresGpu ? "warn" : "neutral"}>{model.requiresGpu ? "GPU" : "CPU"}</Badge>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

export function ModelsPage() {
  const [models, setModels] = useState<ModelCapability[]>([]);
  const [device, setDevice] = useState("cpu");
  const [active, setActive] = useState("Baseline");
  const [viewMode, setViewMode] = useState<ModelView>("cards");
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
        <div className="space-y-5">
          <Tabs<ModelView>
            value={viewMode}
            onChange={setViewMode}
            items={[
              { id: "cards", label: "分层卡片" },
              { id: "timeline", label: "时间线" },
              { id: "tree", label: "科技树" }
            ]}
          />

          {viewMode === "cards" ? (
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
                  <ModelCardArticle key={model.id} model={model} />
                ))}
              </div>
            </div>
          ) : null}

          {viewMode === "timeline" ? <TimelineView models={models} /> : null}
          {viewMode === "tree" ? <TechTreeView models={models} /> : null}
        </div>
      ) : null}
    </div>
  );
}
