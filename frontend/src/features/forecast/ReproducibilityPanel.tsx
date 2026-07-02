import { controls, SectionCard, surface } from "../../shared/components/Ui";
import type { ExperimentManifest } from "../../shared/types/api";

export function ReproducibilityPanel({ experimentId, manifest }: { experimentId: string; manifest: ExperimentManifest | null | undefined }) {
  if (!manifest) {
    return (
      <SectionCard title="实验复现" description="当前运行还没有附带可下载的 Manifest。">
        <div className={`text-sm ${surface.mutedText}`}>请重新运行实验，系统会在保存结果后生成配置哈希、环境信息和目标列快照。</div>
      </SectionCard>
    );
  }

  const configuration = manifest.configuration ?? {};
  const target = manifest.targets[0];
  const targetLabel = target?.targetColumn ?? (manifest.data.targetColumns.join(", ") || "-");
  const covariateLabel = manifest.data.covariateColumns.length ? manifest.data.covariateColumns.join(", ") : "-";
  const featureConfig = (configuration.featureConfig as Record<string, boolean> | undefined) ?? {};
  const featureConfigLabel = Object.entries(featureConfig)
    .filter(([, enabled]) => Boolean(enabled))
    .map(([key]) => key)
    .join(", ") || "-";

  return (
    <SectionCard
      title="实验复现"
      description="配置哈希、源文件哈希、运行环境和目标列快照都会跟随实验一起保存。"
      action={
        <button className={controls.secondaryButton} onClick={() => window.open(`/api/experiments/${experimentId}/manifest/download`, "_blank")}>
          下载 Manifest
        </button>
      }
    >
      <div className="grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-3">
        {[
          ["配置 Hash", manifest.configHash],
          ["源文件 Hash", manifest.sourceFileSha256],
          ["运行模式", String((configuration.runProfile as string | undefined) ?? "balanced")],
          ["参数策略", String((configuration.parameterStrategy as string | undefined) ?? "default")],
          ["随机种子", String((configuration.randomSeed as number | undefined) ?? 42)],
          ["应用版本", manifest.environment.appVersion],
          ["Git Commit", manifest.environment.gitCommit ?? "-"],
          ["运行设备", manifest.environment.device],
          ["Python 版本", manifest.environment.pythonVersion],
          ["目标列", targetLabel],
          ["协变量列", covariateLabel],
          ["featureConfig", featureConfigLabel],
          ["识别频率", target?.detectedFrequency ?? "-"],
          ["推荐模型", target?.recommendedModelId ?? "-"],
        ].map(([label, value]) => (
          <div key={label} className={`${surface.softPanel} p-4`}>
            <div className={`text-xs ${surface.mutedText}`}>{label}</div>
            <div className={`mt-2 break-all font-medium ${surface.strongText}`}>{value}</div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
