import { useEffect, useMemo } from "react";
import { SideDrawer } from "../../shared/components/Ui";
import type { RuntimeRunDetail } from "../../shared/types/api";
import { RuntimeInspectorPanel } from "./RuntimeInspectorPanel";

function stageLabel(stage: RuntimeRunDetail["currentStage"]) {
  return {
    pending: "Pending",
    loading: "Loading",
    cleaning: "Cleaning",
    feature_engineering: "Feature Engineering",
    feature_selection: "Feature Selection",
    auto_tuning: "Auto Tuning",
    training: "Training",
    forecast: "Forecast",
    residual_analysis: "Residual Analysis",
    finished: "Finished",
    failed: "Failed"
  }[stage] ?? stage;
}

function modelKey(model: { targetColumn: string; modelId: string }) {
  return `${model.targetColumn}:${model.modelId}`;
}

export function RuntimeModelConsoleDrawer({
  runtime,
  selectedModelKey,
  open,
  onClose
}: {
  runtime: RuntimeRunDetail | null;
  selectedModelKey: string;
  open: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  const filteredRuntime = useMemo<RuntimeRunDetail | null>(() => {
    if (!runtime || !selectedModelKey) return null;
    const selectedModel = runtime.models.find((model) => modelKey(model) === selectedModelKey);
    if (!selectedModel) return null;
    const matchingModelId = selectedModel.modelId;
    const matchingTarget = selectedModel.targetColumn;
    return {
      ...runtime,
      currentStage: selectedModel.currentStage,
      currentStageLabel: stageLabel(selectedModel.currentStage),
      overallPercent: selectedModel.progressPercent,
      message: selectedModel.message,
      currentTarget: matchingTarget,
      estimatedTotalSeconds: selectedModel.estimatedSeconds,
      estimatedRemainingSeconds: selectedModel.estimatedRemainingSeconds,
      elapsedSeconds: selectedModel.elapsedSeconds,
      models: [selectedModel],
      logs: runtime.logs.filter((entry) => !entry.modelId || (entry.modelId === matchingModelId && (!entry.targetColumn || entry.targetColumn === matchingTarget))),
      timeline: runtime.timeline.filter((entry) => !entry.modelId || (entry.modelId === matchingModelId && (!entry.targetColumn || entry.targetColumn === matchingTarget))),
      events: runtime.events.filter((entry) => !entry.modelId || (entry.modelId === matchingModelId && (!entry.targetColumn || entry.targetColumn === matchingTarget))),
      featurePipeline: runtime.featurePipeline.filter((target) => target.targetColumn === matchingTarget),
      optimization: runtime.optimization.filter((item) => item.modelId === matchingModelId && item.targetColumn === matchingTarget),
      error: selectedModel.error ?? runtime.error
    };
  }, [runtime, selectedModelKey]);

  const selectedModel = filteredRuntime?.models[0] ?? null;

  return (
    <SideDrawer
      open={open && Boolean(filteredRuntime)}
      onClose={onClose}
      title={selectedModel ? `${selectedModel.modelName} · Model Console` : "Model Console"}
      description={selectedModel ? `目标列：${selectedModel.targetColumn} · ${selectedModel.computeTarget.toUpperCase()} · 点击遮罩或按 Esc 可收起。` : undefined}
      widthClassName="w-full max-w-[960px]"
    >
      <RuntimeInspectorPanel
        runtime={filteredRuntime}
        title="Model Console Drawer"
        description="这里聚合同一个模型的阶段状态、优化轨迹、特征工厂、日志与时间线。"
        className="border-0 bg-transparent p-0 shadow-none"
      />
    </SideDrawer>
  );
}
