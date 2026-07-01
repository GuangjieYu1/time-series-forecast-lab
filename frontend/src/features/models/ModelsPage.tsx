import { useEffect, useMemo, useState } from "react";
import type { ELK, ElkExtendedEdge, ElkNode, ElkPort } from "elkjs/lib/elk.bundled";
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

type ElkGraphMode = "timeline" | "tree";
type PortSide = "EAST" | "WEST" | "NORTH" | "SOUTH";

interface LayoutPort {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  kind: "source" | "target";
}

interface LayoutNode extends VisualNode {
  ports: LayoutPort[];
}

interface LayoutEdge {
  id: string;
  edge: GraphEdge;
  paths: string[];
}

interface ElkGraphLayout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  width: number;
  height: number;
}

const timelineLanes = ["基线模型", "统计模型", "机器学习", "深度学习", "Transformer", "基础模型"];
const timelineYears = [1900, 1957, 1960, 1970, 2001, 2016, 2017, 2019, 2021, 2022, 2023, 2024];
const recommendedPath = new Set(["seasonal_naive", "ets", "prophet", "lightgbm", "patchtst", "timesfm"]);
const graphInset = 36;
let elkInstance: ELK | null = null;

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

const techTreeEdges: GraphEdge[] = [
  { from: "moving_average", to: "lag_features" },
  { from: "naive", to: "arima" },
  { from: "seasonal_naive", to: "ets", recommended: true },
  { from: "arima", to: "sarima" },
  { from: "ets", to: "theta" },
  { from: "ets", to: "tbats" },
  { from: "ets", to: "prophet", recommended: true },
  { from: "lag_features", to: "random_forest" },
  { from: "lag_features", to: "xgboost" },
  { from: "lag_features", to: "lightgbm" },
  { from: "lag_features", to: "catboost" },
  { from: "random_forest", to: "nbeats" },
  { from: "xgboost", to: "deepar" },
  { from: "lightgbm", to: "patchtst", recommended: true },
  { from: "nbeats", to: "nhits" },
  { from: "deepar", to: "tft" },
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
  core: { width: 148, height: 72 },
  normal: { width: 138, height: 68 },
  small: { width: 120, height: 62 }
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

function edgeKey(edge: GraphEdge) {
  return `${edge.from}->${edge.to}`;
}

function layoutOrder(node: VisualNode) {
  const laneIndex = timelineLanes.indexOf(node.lane);
  const yearIndex = timelineYears.indexOf(node.year);
  return `${Math.max(yearIndex, 0).toString().padStart(2, "0")}-${Math.max(laneIndex, 0).toString().padStart(2, "0")}-${node.id}`;
}

function portId(nodeId: string, kind: "source" | "target", index: number) {
  return `${nodeId}__${kind}__${index}`;
}

function edgePath(section: NonNullable<ElkExtendedEdge["sections"]>[number]) {
  const points = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

function buildPorts(nodeId: string, edges: GraphEdge[], sourceSide: PortSide, targetSide: PortSide): ElkPort[] {
  const ports: ElkPort[] = [];
  edges.forEach((edge, index) => {
    if (edge.from === nodeId) {
      ports.push({
        id: portId(nodeId, "source", index),
        width: 8,
        height: 8,
        layoutOptions: { "elk.port.side": sourceSide }
      });
    }
    if (edge.to === nodeId) {
      ports.push({
        id: portId(nodeId, "target", index),
        width: 8,
        height: 8,
        layoutOptions: { "elk.port.side": targetSide }
      });
    }
  });
  return ports;
}

function layoutPorts(ports: ElkPort[] | undefined): LayoutPort[] {
  return (ports ?? []).map((port) => ({
    id: port.id,
    x: port.x ?? 0,
    y: port.y ?? 0,
    width: port.width ?? 8,
    height: port.height ?? 8,
    kind: port.id.includes("__source__") ? "source" : "target"
  }));
}

async function getElk() {
  if (!elkInstance) {
    const { default: ElkConstructor } = await import("elkjs/lib/elk.bundled");
    elkInstance = new ElkConstructor();
  }
  return elkInstance;
}

async function layoutWithElk(nodes: VisualNode[], edges: GraphEdge[], mode: ElkGraphMode): Promise<ElkGraphLayout> {
  const elk = await getElk();
  const sizeMap = mode === "timeline" ? timelineNodeSize : nodeSize;
  const sourceSide: PortSide = mode === "timeline" ? "EAST" : "SOUTH";
  const targetSide: PortSide = mode === "timeline" ? "WEST" : "NORTH";
  const sortedNodes = [...nodes].sort((left, right) => layoutOrder(left).localeCompare(layoutOrder(right)));
  const children: ElkNode[] = sortedNodes.map((node) => {
    const size = sizeMap[node.tier];
    return {
      id: node.id,
      width: size.width,
      height: size.height,
      ports: buildPorts(node.id, edges, sourceSide, targetSide),
      layoutOptions: {
        "elk.portConstraints": "FIXED_SIDE",
        "elk.nodeLabels.placement": "INSIDE CENTER"
      }
    };
  });

  const elkEdges: ElkExtendedEdge[] = edges.map((edge, index) => ({
    id: edgeKey(edge),
    sources: [portId(edge.from, "source", index)],
    targets: [portId(edge.to, "target", index)]
  }));

  const baseOptions: Record<string, string> =
    mode === "timeline"
      ? {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.edgeRouting": "ORTHOGONAL",
          "elk.spacing.nodeNode": "44",
          "elk.spacing.edgeNode": "18",
          "elk.layered.spacing.nodeNodeBetweenLayers": "88",
          "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
          "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
          "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX"
        }
      : {
          "elk.algorithm": "mrtree",
          "elk.direction": "DOWN",
          "elk.edgeRouting": "POLYLINE",
          "elk.spacing.nodeNode": "38",
          "elk.mrtree.edgeRoutingMode": "AVOID_OVERLAP"
        };

  const graphInput: ElkNode = {
    id: `${mode}-model-graph`,
    children,
    edges: elkEdges,
    layoutOptions: baseOptions
  };
  const graph = await elk.layout(graphInput);

  const childrenById = new Map((graph.children ?? []).map((node) => [node.id, node]));
  const edgeMeta = new Map(edges.map((edge) => [edgeKey(edge), edge]));
  const layoutNodes = sortedNodes.map((node) => {
    const laidOut = childrenById.get(node.id);
    return {
      ...node,
      x: laidOut?.x ?? 0,
      y: laidOut?.y ?? 0,
      ports: layoutPorts(laidOut?.ports)
    };
  });
  const layoutEdges = (graph.edges ?? []).map((edge) => ({
    id: edge.id,
    edge: edgeMeta.get(edge.id) ?? { from: "", to: "" },
    paths: (edge.sections ?? []).map(edgePath)
  }));
  const extents = layoutNodes.reduce(
    (acc, node) => {
      const size = sizeMap[node.tier];
      return {
        width: Math.max(acc.width, node.x + size.width),
        height: Math.max(acc.height, node.y + size.height)
      };
    },
    { width: graph.width ?? 0, height: graph.height ?? 0 }
  );

  return {
    nodes: layoutNodes,
    edges: layoutEdges,
    width: Math.max(mode === "timeline" ? 1320 : 960, extents.width + graphInset * 2),
    height: Math.max(mode === "timeline" ? 680 : 760, extents.height + graphInset * 2)
  };
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
  compact = false,
  showHandles = false
}: {
  node: VisualNode & { ports?: LayoutPort[] };
  hoveredId: string | null;
  relatedIds: Set<string>;
  onHover: (nodeId: string | null) => void;
  onOpen: (node: VisualNode) => void;
  compact?: boolean;
  showHandles?: boolean;
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
      style={{ left: node.x, top: node.y, width: size.width, height: size.height }}
    >
      {showHandles
        ? node.ports?.map((port) => (
            <span
              key={port.id}
              className={`pointer-events-none absolute z-30 h-2.5 w-2.5 rounded-full border shadow-[0_0_12px_rgba(34,211,238,0.55)] ${
                port.kind === "source" ? "border-cyan-200 bg-cyan-300" : "border-violet-200 bg-violet-300"
              }`}
              style={{
                left: port.x - 5,
                top: port.y - 5
              }}
            />
          ))
        : null}
      <div className={`${compact ? "p-2.5" : node.tier === "small" ? "p-2.5" : "p-3.5"}`}>
        <div className="flex items-start justify-between gap-2">
          <div className={`font-semibold leading-tight ${tierClass}`}>{node.name}</div>
          <span className="rounded-full border border-white/10 bg-white/8 px-1.5 py-0.5 text-[10px] font-semibold text-slate-200">{modelIcon(node.model, node)}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="rounded-full border border-white/10 bg-white/8 px-2 py-0.5 text-[10px] text-slate-200">{node.year}</span>
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

function ElkGraphView({
  title,
  description,
  nodes,
  edges,
  mode,
  onOpen
}: {
  title: string;
  description: string;
  nodes: VisualNode[];
  edges: GraphEdge[];
  mode: ElkGraphMode;
  onOpen: (node: VisualNode) => void;
}) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [layout, setLayout] = useState<ElkGraphLayout | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const related = useMemo(() => collectRelated(hoveredId, edges), [hoveredId, edges]);
  const nodeMap = useMemo(() => new Map((layout?.nodes ?? nodes).map((node) => [node.id, node])), [layout?.nodes, nodes]);
  const routeGradientId = `${mode}Route`;
  const routeGlowId = `${mode}Glow`;
  const arrowId = `${mode}Arrow`;

  useEffect(() => {
    let mounted = true;
    setLayout(null);
    setLayoutError(null);
    void layoutWithElk(nodes, edges, mode)
      .then((result) => {
        if (mounted) setLayout(result);
      })
      .catch((err) => {
        if (mounted) setLayoutError(err instanceof Error ? err.message : "ELK 布局计算失败。");
      });
    return () => {
      mounted = false;
    };
  }, [edges, mode, nodes]);

  return (
    <SectionCard title={title} description={description}>
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
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">{mode === "timeline" ? "ELKjs Multiple Handles" : "ELKjs Tree"}</div>
            <div className="mt-1 text-lg font-semibold text-white">{mode === "timeline" ? "多端口模型演化图" : "自上而下模型科技树"}</div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-slate-300">
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-6 rounded-full bg-gradient-to-r from-cyan-300 to-violet-400 shadow-[0_0_12px_rgba(129,140,248,0.8)]" />推荐主干</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-cyan-300" />可运行</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-300" />未安装</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-violet-300" />需下载</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-500" />计划中</span>
          </div>
        </div>

        {layoutError ? <ErrorBanner message={layoutError} /> : null}
        {!layout && !layoutError ? <LoadingBlock label="正在计算 ELK 布局..." /> : null}
        {layout ? (
          <div className="relative" style={{ minWidth: layout.width, height: layout.height }}>
            <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${layout.width} ${layout.height}`} preserveAspectRatio="none">
              <defs>
                <linearGradient id={routeGradientId} x1="0" x2="1" y1="0" y2="0">
                  <stop offset="0%" stopColor="#22D3EE" />
                  <stop offset="100%" stopColor="#A78BFA" />
                </linearGradient>
                <filter id={routeGlowId} x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="4" result="coloredBlur" />
                  <feMerge>
                    <feMergeNode in="coloredBlur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <marker id={arrowId} markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto" markerUnits="strokeWidth">
                  <path d="M 0 0 L 8 4 L 0 8 z" fill="#67E8F9" opacity="0.78" />
                </marker>
              </defs>
              <g transform={`translate(${graphInset} ${graphInset})`}>
                {layout.edges.map((layoutEdge) => {
                  const key = layoutEdge.id;
                  const isRelated = !hoveredId || related.edgeIds.has(key);
                  const from = nodeMap.get(layoutEdge.edge.from);
                  const to = nodeMap.get(layoutEdge.edge.to);
                  const planned = isPlannedNode(from) || isPlannedNode(to);
                  return layoutEdge.paths.map((path, index) => (
                    <path
                      key={`${key}:${index}`}
                      d={path}
                      fill="none"
                      markerEnd={isRelated ? `url(#${arrowId})` : undefined}
                      stroke={layoutEdge.edge.recommended ? `url(#${routeGradientId})` : planned ? "rgba(148,163,184,0.34)" : "rgba(125,211,252,0.28)"}
                      strokeWidth={layoutEdge.edge.recommended ? (isRelated ? 4.6 : 3) : isRelated ? 2.1 : 1.1}
                      strokeDasharray={planned && !layoutEdge.edge.recommended ? "8 8" : undefined}
                      opacity={isRelated ? (layoutEdge.edge.recommended ? 0.98 : planned ? 0.44 : 0.62) : 0.1}
                      filter={layoutEdge.edge.recommended && isRelated ? `url(#${routeGlowId})` : undefined}
                    />
                  ));
                })}
              </g>
            </svg>

            {layout.nodes.map((node) => (
              <MapNode
                key={node.id}
                node={{ ...node, x: node.x + graphInset, y: node.y + graphInset }}
                hoveredId={hoveredId}
                relatedIds={related.nodeIds}
                onHover={setHoveredId}
                onOpen={onOpen}
                compact={mode === "timeline"}
                showHandles
              />
            ))}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

function TechTreeView({ nodes, onOpen }: { nodes: VisualNode[]; onOpen: (node: VisualNode) => void }) {
  return (
    <ElkGraphView
      title="模型科技树"
      description="ELKjs Tree 自上而下排列主路线和分支节点，点击节点打开详情。"
      nodes={nodes}
      edges={techTreeEdges}
      mode="tree"
      onOpen={onOpen}
    />
  );
}

function TimelineView({ nodes, onOpen }: { nodes: VisualNode[]; onOpen: (node: VisualNode) => void }) {
  return (
    <ElkGraphView
      title="模型发展时间线"
      description="ELKjs Multiple Handles 使用独立输入/输出端口呈现模型依赖和演化关系。"
      nodes={nodes}
      edges={graphEdges}
      mode="timeline"
      onOpen={onOpen}
    />
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
