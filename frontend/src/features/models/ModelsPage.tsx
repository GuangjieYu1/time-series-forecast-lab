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
type NodeTier = "core" | "normal" | "small";
type NodeStatus = ModelCapability["installStatus"] | "planned";

interface VisualNodeBase {
  id: string;
  name: string;
  category: string;
  lane: string;
  year: number;
  tier: NodeTier;
  x: number;
  y: number;
  summary: string;
  registryId?: string;
  recommended?: boolean;
}

interface VisualNode extends VisualNodeBase {
  model: ModelCapability | null;
  status: NodeStatus;
  enabledInMvp: boolean;
}

interface GraphEdge {
  from: string;
  to: string;
  recommended?: boolean;
}

const timelineLanes = ["基线模型", "统计模型", "机器学习", "深度学习", "Transformer", "基础模型"];
const timelineYears = [1900, 1957, 1960, 1970, 2001, 2016, 2017, 2019, 2021, 2022, 2023, 2024];
const recommendedPath = new Set(["seasonal_naive", "ets", "prophet", "lightgbm", "patchtst", "timesfm"]);
const timelineLeft = 178;
const timelineTop = 96;
const timelineYearGap = 156;
const timelineLaneGap = 200;
const timelineWidth = 2160;
const timelineHeight = 1280;

const visualNodes: VisualNodeBase[] = [
  { id: "moving_average", name: "Moving Average", category: "Baseline", lane: "基线模型", year: 1900, tier: "normal", x: 150, y: 54, summary: "早期平滑思想，用最近窗口平均值构造稳定基线。" },
  { id: "linear_trend", name: "Linear Trend", category: "Baseline", lane: "基线模型", year: 1960, tier: "small", x: 1032, y: 56, summary: "线性趋势外推，是解释性强但表达力有限的基线扩展。" },
  { id: "naive", name: "Naive", category: "Baseline", lane: "基线模型", year: 1960, tier: "normal", x: 450, y: 54, summary: "未来值等于最近一次观测，是所有复杂模型的最低基准。" },
  { id: "seasonal_naive", name: "Seasonal Naive", category: "Baseline", lane: "基线模型", year: 1960, tier: "normal", x: 668, y: 50, summary: "复用上一周期同位置值，适合强季节性序列。", recommended: true },
  { id: "lag_features", name: "Lag Features", category: "Machine Learning", lane: "机器学习", year: 2001, tier: "small", x: 170, y: 196, summary: "把历史滞后、滚动统计和日历信息转成机器学习特征。" },

  { id: "arima", name: "ARIMA", category: "Statistical", lane: "统计模型", year: 1970, tier: "normal", x: 430, y: 186, summary: "用自回归、差分和移动平均描述序列自相关结构。" },
  { id: "ets", name: "ETS", category: "Statistical", lane: "统计模型", year: 1957, tier: "normal", x: 668, y: 184, summary: "指数平滑模型族，建模误差、趋势和季节性。", recommended: true },
  { id: "sarima", name: "SARIMA", category: "Statistical", lane: "统计模型", year: 1975, tier: "small", x: 352, y: 324, summary: "ARIMA 的季节性扩展，适合固定季节周期。" },
  { id: "theta", name: "Theta", category: "Statistical", lane: "统计模型", year: 2000, tier: "small", x: 510, y: 326, summary: "通过 Theta 线分解趋势和短期波动的统计模型。" },
  { id: "tbats", name: "TBATS", category: "Statistical", lane: "统计模型", year: 2011, tier: "small", x: 934, y: 326, summary: "面向复杂多季节性的指数平滑扩展。" },
  { id: "prophet", name: "Prophet", category: "Statistical", lane: "统计模型", year: 2017, tier: "core", x: 656, y: 318, summary: "可解释的可加模型，强调趋势、季节性和节假日效应。", recommended: true },

  { id: "random_forest", name: "Random Forest", category: "Machine Learning", lane: "机器学习", year: 2001, tier: "normal", x: 96, y: 466, summary: "集成树模型，依赖滞后特征和滚动窗口做递归预测。" },
  { id: "xgboost", name: "XGBoost", category: "Machine Learning", lane: "机器学习", year: 2016, tier: "core", x: 358, y: 458, summary: "高性能 GBDT，对结构化时序特征非常强。" },
  { id: "lightgbm", name: "LightGBM", category: "Machine Learning", lane: "机器学习", year: 2017, tier: "core", x: 656, y: 456, summary: "更轻量高效的 GBDT，是工业预测中常用强基线。", recommended: true },
  { id: "catboost", name: "CatBoost", category: "Machine Learning", lane: "机器学习", year: 2017, tier: "small", x: 1000, y: 476, summary: "梯度提升树路线的扩展节点，适合类别特征较多的业务表。" },

  { id: "nbeats", name: "N-BEATS", category: "Deep Learning", lane: "深度学习", year: 2019, tier: "normal", x: 82, y: 606, summary: "神经基展开模型，强调可解释分解和单变量预测能力。" },
  { id: "nhits", name: "N-HiTS", category: "Deep Learning", lane: "深度学习", year: 2022, tier: "normal", x: 82, y: 742, summary: "层级插值深度模型，面向长预测步长。" },
  { id: "deepar", name: "DeepAR", category: "Deep Learning", lane: "深度学习", year: 2017, tier: "small", x: 1000, y: 610, summary: "概率深度预测模型，适合批量相关序列。" },
  { id: "tft", name: "TFT", category: "Deep Learning", lane: "Transformer", year: 2021, tier: "small", x: 1000, y: 742, summary: "Temporal Fusion Transformer，强调可解释多变量预测。" },
  { id: "patchtst", name: "PatchTST", category: "Deep Learning", lane: "Transformer", year: 2023, tier: "core", x: 656, y: 612, summary: "Patch 化 Transformer，把长时序切片后建模。", recommended: true },

  { id: "timesfm", name: "TimesFM", category: "Foundation Model", lane: "基础模型", year: 2023, tier: "core", x: 656, y: 784, summary: "Google 时序基础模型，强调跨领域 zero-shot 预测能力。", recommended: true },
  { id: "chronos", name: "Chronos", category: "Foundation Model", lane: "基础模型", year: 2024, tier: "core", x: 406, y: 790, summary: "Amazon 时序基础模型，把时间序列 token 化后接入语言模型范式。" },
  { id: "moirai", name: "Moirai", category: "Foundation Model", lane: "基础模型", year: 2024, tier: "core", x: 902, y: 790, summary: "Salesforce 通用时序基础模型，强调跨领域统一训练。" },
  { id: "lag_llama", name: "Lag-Llama", category: "Foundation Model", lane: "基础模型", year: 2023, tier: "small", x: 1130, y: 810, summary: "Llama 风格概率时序基础模型路线。" }
];

const graphEdges: GraphEdge[] = [
  { from: "moving_average", to: "lag_features" },
  { from: "naive", to: "arima" },
  { from: "naive", to: "ets" },
  { from: "seasonal_naive", to: "ets", recommended: true },
  { from: "arima", to: "sarima" },
  { from: "arima", to: "prophet" },
  { from: "ets", to: "theta" },
  { from: "ets", to: "tbats" },
  { from: "ets", to: "prophet", recommended: true },
  { from: "lag_features", to: "random_forest" },
  { from: "lag_features", to: "xgboost" },
  { from: "lag_features", to: "lightgbm" },
  { from: "lag_features", to: "catboost" },
  { from: "prophet", to: "lightgbm", recommended: true },
  { from: "random_forest", to: "nbeats" },
  { from: "xgboost", to: "patchtst" },
  { from: "lightgbm", to: "patchtst", recommended: true },
  { from: "nbeats", to: "nhits" },
  { from: "deepar", to: "tft" },
  { from: "tft", to: "patchtst" },
  { from: "patchtst", to: "timesfm", recommended: true },
  { from: "patchtst", to: "chronos" },
  { from: "patchtst", to: "moirai" },
  { from: "patchtst", to: "lag_llama" }
];

const nodeSize: Record<NodeTier, { width: number; height: number }> = {
  core: { width: 176, height: 96 },
  normal: { width: 150, height: 82 },
  small: { width: 116, height: 62 }
};

const timelineNodeSize: Record<NodeTier, { width: number; height: number }> = {
  core: { width: 138, height: 58 },
  normal: { width: 124, height: 52 },
  small: { width: 106, height: 46 }
};

function modelIcon(model: ModelCapability | null, node?: VisualNode) {
  if (model?.isFoundationModel || node?.category === "Foundation Model") return "FM";
  if (model?.modelFamily === "Deep Learning" || node?.category === "Deep Learning") return "DL";
  if (model?.modelFamily === "Machine Learning" || node?.category === "Machine Learning") return "ML";
  if (model?.category === "Statistical" || node?.category === "Statistical") return "ST";
  return "BL";
}

function statusTone(status: NodeStatus): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "available") return "good";
  if (status === "downloading") return "info";
  if (status === "failed") return "bad";
  if (status === "planned") return "neutral";
  return "warn";
}

function statusText(status: NodeStatus) {
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

function buildNodes(models: ModelCapability[]) {
  const byId = new Map(models.map((model) => [model.id, model]));
  return visualNodes.map((node) => {
    const model = byId.get(node.registryId ?? node.id) ?? null;
    return {
      ...node,
      model,
      status: model?.installStatus ?? "planned",
      enabledInMvp: Boolean(model?.enabledInMvp)
    };
  });
}

function nodeStatusClass(node: VisualNode) {
  if (!node.model || node.status === "planned") {
    return "border-slate-500/25 bg-slate-900/48 text-slate-300 opacity-70";
  }
  if (node.status === "available") {
    return "border-cyan-300/45 bg-cyan-300/[0.08] text-cyan-50 shadow-[0_0_26px_rgba(34,211,238,0.14)]";
  }
  if (node.status === "downloading") {
    return "border-violet-300/70 bg-violet-400/[0.10] text-violet-50";
  }
  if (node.status === "failed") {
    return "border-red-300/70 bg-red-400/[0.10] text-red-50";
  }
  return "border-amber-300/70 bg-amber-300/[0.10] text-amber-50";
}

function isPlannedNode(node: VisualNode | undefined) {
  return !node?.model || node.status === "planned" || !node.enabledInMvp;
}

function nodeCenter(node: VisualNode, sizeMap = nodeSize) {
  const size = sizeMap[node.tier];
  return { x: node.x + size.width / 2, y: node.y + size.height / 2 };
}

function nodePort(node: VisualNode, side: "top" | "bottom", sizeMap = nodeSize) {
  const size = sizeMap[node.tier];
  return { x: node.x + size.width / 2, y: side === "top" ? node.y : node.y + size.height };
}

function edgeKey(edge: GraphEdge) {
  return `${edge.from}->${edge.to}`;
}

function collectRelated(nodeId: string | null, edges: GraphEdge[]) {
  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  if (!nodeId) return { nodeIds, edgeIds };
  nodeIds.add(nodeId);

  function walkForward(id: string) {
    edges.filter((edge) => edge.from === id).forEach((edge) => {
      const key = edgeKey(edge);
      if (edgeIds.has(key)) return;
      edgeIds.add(key);
      nodeIds.add(edge.to);
      walkForward(edge.to);
    });
  }

  function walkBackward(id: string) {
    edges.filter((edge) => edge.to === id).forEach((edge) => {
      const key = edgeKey(edge);
      if (edgeIds.has(key)) return;
      edgeIds.add(key);
      nodeIds.add(edge.from);
      walkBackward(edge.from);
    });
  }

  walkForward(nodeId);
  walkBackward(nodeId);
  return { nodeIds, edgeIds };
}

function curvePath(from: { x: number; y: number }, to: { x: number; y: number }) {
  if (Math.abs(to.y - from.y) > Math.abs(to.x - from.x) * 0.75) {
    const dy = Math.max(82, Math.abs(to.y - from.y) * 0.46);
    const bend = Math.min(54, Math.abs(to.x - from.x) * 0.12);
    return `M ${from.x} ${from.y} C ${from.x + bend} ${from.y + dy}, ${to.x - bend} ${to.y - dy}, ${to.x} ${to.y}`;
  }
  const dx = Math.max(80, Math.abs(to.x - from.x) * 0.48);
  const sway = Math.min(84, Math.abs(to.y - from.y) * 0.22);
  return `M ${from.x} ${from.y} C ${from.x + dx} ${from.y + sway}, ${to.x - dx} ${to.y - sway}, ${to.x} ${to.y}`;
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

function MapNode({
  node,
  hoveredId,
  relatedIds,
  onHover,
  onOpen,
  compact = false
}: {
  node: VisualNode;
  hoveredId: string | null;
  relatedIds: Set<string>;
  onHover: (nodeId: string | null) => void;
  onOpen: (node: VisualNode) => void;
  compact?: boolean;
}) {
  const size = (compact ? timelineNodeSize : nodeSize)[node.tier];
  const related = !hoveredId || relatedIds.has(node.id);
  const tierClass = node.tier === "core" ? "text-sm" : node.tier === "normal" ? "text-xs" : "text-[11px]";
  const recommended = node.recommended || recommendedPath.has(node.id);
  return (
    <button
      type="button"
      title={`${node.name}: ${node.summary}`}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(node.id)}
      onBlur={() => onHover(null)}
      onClick={() => onOpen(node)}
      className={`group absolute z-20 rounded-2xl border text-left backdrop-blur-xl transition duration-200 ${nodeStatusClass(node)} ${
        recommended ? "ring-1 ring-violet-300/60 shadow-[0_0_34px_rgba(129,140,248,0.35)]" : ""
      } ${related ? "opacity-100" : "opacity-30 saturate-50"}`}
      style={{ left: node.x, top: node.y, width: size.width, minHeight: size.height }}
    >
      <div className={`${compact ? "p-2.5" : node.tier === "small" ? "p-2.5" : "p-3.5"}`}>
        <div className="flex items-start justify-between gap-2">
          <div className={`font-semibold leading-tight ${tierClass}`}>{node.name}</div>
          <span className="rounded-full border border-white/10 bg-white/8 px-1.5 py-0.5 text-[10px] font-semibold text-slate-200">{modelIcon(node.model, node)}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="rounded-full border border-white/10 bg-white/8 px-2 py-0.5 text-[10px] text-slate-200">{statusText(node.status)}</span>
          {recommended ? <span className="rounded-full bg-violet-400/20 px-2 py-0.5 text-[10px] text-violet-100">主干</span> : null}
        </div>
      </div>
      <div className="pointer-events-none absolute left-0 top-full z-50 mt-2 hidden w-64 rounded-xl border border-cyan-300/20 bg-[#08111f]/95 p-3 text-xs leading-5 text-slate-200 shadow-2xl shadow-cyan-950/40 group-hover:block">
        <div className="font-semibold text-white">{node.year} · {node.name}</div>
        <div className="mt-1 text-slate-300">{node.summary}</div>
        <div className="mt-2 text-slate-400">{node.model ? "来自模型注册表，可用性随后端检测更新。" : "路线图预留节点，不能在实验页选择。"}</div>
      </div>
    </button>
  );
}

function ModelDetailDrawer({ node, onClose }: { node: VisualNode | null; onClose: () => void }) {
  if (!node) return null;
  const model = node.model;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/50 backdrop-blur-sm" onClick={onClose}>
      <aside className="h-full w-full max-w-md overflow-y-auto border-l border-white/10 bg-[#08111f] p-6 text-slate-100 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">{node.category}</div>
            <h2 className="mt-2 text-2xl font-semibold text-white">{node.name}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-300">{node.summary}</p>
          </div>
          <button type="button" className="rounded-full border border-white/10 px-3 py-1 text-sm text-slate-300 hover:bg-white/10" onClick={onClose}>关闭</button>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="text-xs text-slate-400">出现时间</div>
            <div className="mt-1 text-lg font-semibold">{node.year}</div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="text-xs text-slate-400">节点层级</div>
            <div className="mt-1 text-lg font-semibold">{node.tier === "core" ? "核心节点" : node.tier === "normal" ? "普通节点" : "扩展节点"}</div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="text-xs text-slate-400">当前状态</div>
            <div className="mt-2"><Badge tone={statusTone(node.status)}>{statusText(node.status)}</Badge></div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="text-xs text-slate-400">实验可选</div>
            <div className="mt-2"><Badge tone={node.enabledInMvp && node.status === "available" ? "good" : "neutral"}>{node.enabledInMvp && node.status === "available" ? "可选" : "不可选"}</Badge></div>
          </div>
        </div>

        {model ? (
          <>
            <div className="mt-5 rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-sm font-semibold text-white">模型说明</div>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                {zhCN.modelDescriptions[model.id as keyof typeof zhCN.modelDescriptions] ?? model.shortDescription}
              </p>
              {model.unavailableReason ? <p className="mt-3 rounded-xl border border-amber-300/20 bg-amber-300/10 p-3 text-xs text-amber-100">{model.unavailableReason}</p> : null}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {capabilityBadges(model).map((badge) => (
                <Badge key={badge.label} tone={badge.tone}>{badge.label}</Badge>
              ))}
            </div>
            {(model.paperUrl ?? model.representativePaperUrl) ? (
              <a className="mt-5 inline-flex text-sm font-semibold text-cyan-300 hover:underline" href={model.paperUrl ?? model.representativePaperUrl ?? undefined} target="_blank" rel="noreferrer">
                代表论文：{model.paperTitle ?? model.representativePaperTitle ?? "查看论文"}
              </a>
            ) : null}
          </>
        ) : (
          <div className="mt-5 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-slate-300">
            这是技术路线图预留节点，目前没有进入后端模型注册表，因此不会出现在预测实验的可选模型中。
          </div>
        )}
      </aside>
    </div>
  );
}

function TechTreeView({ nodes, onOpen }: { nodes: VisualNode[]; onOpen: (node: VisualNode) => void }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const related = useMemo(() => collectRelated(hoveredId, graphEdges), [hoveredId]);

  return (
    <SectionCard title="模型科技树" description="多分支、汇聚和主干路线展示。hover 节点高亮上游和下游路径，点击节点打开详情。">
      <div
        className="relative -mx-4 touch-pan-x overflow-auto rounded-[22px] border border-cyan-300/10 bg-[#08111f] p-3 shadow-[0_28px_120px_rgba(2,8,23,0.45)] sm:mx-0 sm:rounded-[28px] sm:p-4"
        style={{
          backgroundImage:
            "radial-gradient(circle at 18% 12%, rgba(129,140,248,0.18), transparent 28%), radial-gradient(circle at 76% 22%, rgba(34,211,238,0.12), transparent 30%), linear-gradient(rgba(148,163,184,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.06) 1px, transparent 1px)",
          backgroundSize: "auto, auto, 28px 28px, 28px 28px"
        }}
      >
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 px-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">AI Model Roadmap</div>
            <div className="mt-1 text-lg font-semibold text-white">企业级时间序列模型技术地图</div>
            <div className="mt-1 text-xs text-slate-400 sm:hidden">横向滑动查看全图，点击节点查看详情。</div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-slate-300">
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-6 rounded-full bg-gradient-to-r from-cyan-300 to-violet-400 shadow-[0_0_12px_rgba(129,140,248,0.8)]" />推荐主干</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-cyan-300" />可运行</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-300" />未安装</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-violet-300" />需下载</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-500" />计划中</span>
          </div>
        </div>

        <div className="relative h-[960px] min-w-[1280px]">
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1280 960" preserveAspectRatio="none">
            <defs>
              <linearGradient id="recommendedStroke" x1="0" x2="1" y1="0" y2="0">
                <stop offset="0%" stopColor="#22D3EE" />
                <stop offset="100%" stopColor="#A78BFA" />
              </linearGradient>
              <filter id="routeGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="4" result="coloredBlur" />
                <feMerge>
                  <feMergeNode in="coloredBlur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            {graphEdges.map((edge) => {
              const from = nodeMap.get(edge.from);
              const to = nodeMap.get(edge.to);
              if (!from || !to) return null;
              const key = edgeKey(edge);
              const isRelated = !hoveredId || related.edgeIds.has(key);
              const planned = isPlannedNode(from) || isPlannedNode(to);
              return (
                <path
                  key={key}
                  d={curvePath(nodePort(from, "bottom"), nodePort(to, "top"))}
                  fill="none"
                  stroke={edge.recommended ? "url(#recommendedStroke)" : planned ? "rgba(148,163,184,0.34)" : "rgba(125,211,252,0.28)"}
                  strokeWidth={edge.recommended ? (isRelated ? 4.8 : 3.2) : isRelated ? 2.2 : 1.2}
                  strokeDasharray={planned && !edge.recommended ? "8 8" : undefined}
                  opacity={isRelated ? (edge.recommended ? 0.98 : planned ? 0.42 : 0.58) : 0.1}
                  filter={edge.recommended && isRelated ? "url(#routeGlow)" : undefined}
                />
              );
            })}
          </svg>

          {nodes.map((node) => (
            <MapNode key={node.id} node={node} hoveredId={hoveredId} relatedIds={related.nodeIds} onHover={setHoveredId} onOpen={onOpen} />
          ))}
        </div>
      </div>
    </SectionCard>
  );
}

function timelinePosition(node: VisualNode, laneOffsets: Map<string, number>) {
  const yearIndex = timelineYears.indexOf(node.year);
  const x = timelineLeft + Math.max(yearIndex, 0) * timelineYearGap + (laneOffsets.get(`${node.lane}:${node.year}:${node.id}:x`) ?? 0);
  const laneIndex = timelineLanes.indexOf(node.lane);
  const y = timelineTop + Math.max(laneIndex, 0) * timelineLaneGap + (laneOffsets.get(`${node.lane}:${node.year}:${node.id}:y`) ?? 0);
  return { ...node, x, y };
}

function TimelineView({ nodes, onOpen }: { nodes: VisualNode[]; onOpen: (node: VisualNode) => void }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const laneOffsets = useMemo(() => {
    const counters = new Map<string, number>();
    const offsets = new Map<string, number>();
    nodes.forEach((node) => {
      const key = `${node.lane}:${node.year}`;
      const index = counters.get(key) ?? 0;
      counters.set(key, index + 1);
      const direction = index % 2 === 0 ? 1 : -1;
      offsets.set(`${node.lane}:${node.year}:${node.id}:x`, index === 0 ? 0 : direction * 18);
      offsets.set(`${node.lane}:${node.year}:${node.id}:y`, index * 68);
    });
    return offsets;
  }, [nodes]);
  const positioned = useMemo(() => nodes.map((node) => timelinePosition(node, laneOffsets)), [nodes, laneOffsets]);
  const nodeMap = useMemo(() => new Map(positioned.map((node) => [node.id, node])), [positioned]);
  const related = useMemo(() => collectRelated(hoveredId, graphEdges), [hoveredId]);

  return (
    <SectionCard title="模型发展时间线" description="多泳道呈现模型演化，节点按年份落位，路线之间用曲线连接。">
      <div className="-mx-4 touch-pan-x overflow-auto rounded-[22px] border border-cyan-300/10 bg-[#08111f] p-3 text-slate-100 shadow-[0_28px_120px_rgba(2,8,23,0.45)] sm:mx-0 sm:rounded-[28px] sm:p-4">
        <div className="mb-3 px-2 text-xs text-slate-400 sm:hidden">横向滑动查看年份轴；同年模型已错位展示，点击节点查看详情。</div>
        <div className="relative h-[1280px] min-w-[2160px]">
          <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${timelineWidth} ${timelineHeight}`} preserveAspectRatio="none">
            <defs>
              <linearGradient id="timelineRoute" x1="0" x2="1" y1="0" y2="0">
                <stop offset="0%" stopColor="#22D3EE" />
                <stop offset="100%" stopColor="#818CF8" />
              </linearGradient>
              <filter id="timelineGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3.5" result="coloredBlur" />
                <feMerge>
                  <feMergeNode in="coloredBlur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            {timelineYears.map((year, index) => {
              const x = timelineLeft + index * timelineYearGap + 58;
              return (
                <g key={year}>
                  <line x1={x} x2={x} y1={48} y2={1236} stroke="rgba(148,163,184,0.09)" />
                  <text x={x} y={32} textAnchor="middle" fill="#94A3B8" fontSize="12" fontWeight="600">{year}</text>
                </g>
              );
            })}
            {timelineLanes.map((lane, index) => {
              const y = timelineTop + index * timelineLaneGap;
              return <line key={lane} x1={20} x2={2110} y1={y + 76} y2={y + 76} stroke="rgba(148,163,184,0.09)" />;
            })}
            {graphEdges.map((edge) => {
              const from = nodeMap.get(edge.from);
              const to = nodeMap.get(edge.to);
              if (!from || !to) return null;
              const key = edgeKey(edge);
              const isRelated = !hoveredId || related.edgeIds.has(key);
              const planned = isPlannedNode(from) || isPlannedNode(to);
              return (
                <path
                  key={key}
                  d={curvePath(nodeCenter(from, timelineNodeSize), nodeCenter(to, timelineNodeSize))}
                  fill="none"
                  stroke={edge.recommended ? "url(#timelineRoute)" : planned ? "rgba(148,163,184,0.30)" : "rgba(125,211,252,0.24)"}
                  strokeWidth={edge.recommended ? (isRelated ? 4 : 2.8) : isRelated ? 1.8 : 1}
                  strokeDasharray={planned && !edge.recommended ? "7 8" : undefined}
                  opacity={isRelated ? (edge.recommended ? 0.98 : 0.48) : 0.1}
                  filter={edge.recommended && isRelated ? "url(#timelineGlow)" : undefined}
                />
              );
            })}
          </svg>

          {timelineLanes.map((lane, index) => (
            <div key={lane} className="absolute left-4 flex h-16 w-32 items-center rounded-2xl border border-white/10 bg-white/5 px-3 text-sm font-semibold text-slate-200" style={{ top: timelineTop - 4 + index * timelineLaneGap }}>
              {lane}
            </div>
          ))}

          {positioned.map((node) => (
            <MapNode key={node.id} node={node} hoveredId={hoveredId} relatedIds={related.nodeIds} onHover={setHoveredId} onOpen={onOpen} compact />
          ))}
        </div>
      </div>
    </SectionCard>
  );
}

export function ModelsPage() {
  const [models, setModels] = useState<ModelCapability[]>([]);
  const [device, setDevice] = useState("cpu");
  const [active, setActive] = useState("Baseline");
  const [viewMode, setViewMode] = useState<ModelView>("cards");
  const [selectedNode, setSelectedNode] = useState<VisualNode | null>(null);
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
  const graphNodes = useMemo(() => buildNodes(models), [models]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="模型库"
        title="模型能力、依赖状态与技术演化路线"
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

          {viewMode === "timeline" ? <TimelineView nodes={graphNodes} onOpen={setSelectedNode} /> : null}
          {viewMode === "tree" ? <TechTreeView nodes={graphNodes} onOpen={setSelectedNode} /> : null}
        </div>
      ) : null}

      <ModelDetailDrawer node={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  );
}
