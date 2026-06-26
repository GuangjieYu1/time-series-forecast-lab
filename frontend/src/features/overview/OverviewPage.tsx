import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { fetchDevice, fetchExperiments, fetchHealth, fetchModels } from "../../shared/api/client";
import { loadDeepSeekSettings } from "../../shared/api/deepseekSettings";
import { Badge, controls, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import { zhCN } from "../../shared/i18n/zhCN";
import type { ExperimentListItem, ModelCapability } from "../../shared/types/api";

const capabilities = [
  { title: "数据导入", detail: "CSV / XLS / XLSX 后端解析，前端只预览前 100 行。" },
  { title: "多模型比较", detail: "基线、统计、机器学习与基础模型统一回测。" },
  { title: "残差分析", detail: "residual = actual - predicted，指标和图表口径一致。" },
  { title: "AI 总结报告", detail: "用 DeepSeek 生成中文业务解释和风险建议。" }
];

export function OverviewPage() {
  const [experiments, setExperiments] = useState<ExperimentListItem[]>([]);
  const [models, setModels] = useState<ModelCapability[]>([]);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [device, setDevice] = useState("检测中");

  useEffect(() => {
    void fetchExperiments().then(setExperiments).catch(() => setExperiments([]));
    void fetchModels().then(setModels).catch(() => setModels([]));
    void fetchHealth().then((health) => setBackendOk(health.ok)).catch(() => setBackendOk(false));
    void fetchDevice().then(setDevice).catch(() => setDevice("未知"));
  }, []);

  const availableModels = models.filter((model) => model.installStatus === "available").length;
  const timesfm = models.find((model) => model.id === "timesfm");
  const latest = experiments[0];
  const deepSeekConfigured = Boolean(loadDeepSeekSettings().apiKey);
  const modelSummary = useMemo(() => `${availableModels}/${models.length || 0} 个模型可运行`, [availableModels, models.length]);

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <section className={`${surface.workbench} relative overflow-hidden p-7 md:p-10`}>
        <div className="absolute right-[-120px] top-[-120px] h-72 w-72 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="absolute bottom-[-140px] left-[20%] h-72 w-72 rounded-full bg-cyan-400/16 blur-3xl" />
        <div className="relative">
          <Badge tone="info">中文 AI 数据分析工作台</Badge>
          <h1 className="mt-6 max-w-4xl text-4xl font-semibold tracking-tight text-slate-950 dark:text-white md:text-6xl">
            {zhCN.productName}
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-8 text-slate-600 dark:text-slate-300">{zhCN.productTagline}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link className={controls.primaryButton} to="/upload">
              开始新实验
            </Link>
            <Link className={controls.secondaryButton} to="/experiments">
              查看历史实验
            </Link>
          </div>
          <div className="mt-10 grid gap-4 md:grid-cols-4">
            {capabilities.map((item) => (
              <div key={item.title} className="rounded-3xl border border-slate-200 bg-white/75 p-5 dark:border-white/10 dark:bg-white/[0.04]">
                <div className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</div>
                <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <aside className="space-y-4">
        <SectionCard title="系统状态" description="本机运行状态和关键模型可用性。">
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
              <span className="text-sm text-slate-500 dark:text-slate-400">后端服务</span>
              <Badge tone={backendOk ? "good" : backendOk === false ? "bad" : "warn"}>{backendOk ? "在线" : backendOk === false ? "离线" : "检测中"}</Badge>
            </div>
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
              <span className="text-sm text-slate-500 dark:text-slate-400">计算设备</span>
              <Badge tone="info">{device}</Badge>
            </div>
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
              <span className="text-sm text-slate-500 dark:text-slate-400">TimesFM</span>
              <Badge tone={timesfm?.installStatus === "available" ? "good" : timesfm?.installStatus === "downloading" ? "warn" : "neutral"}>
                {timesfm?.installStatus === "available" ? "可运行" : timesfm?.installStatus === "downloading" ? "需要下载" : timesfm?.installStatus ?? "未知"}
              </Badge>
            </div>
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 p-3 dark:bg-[#151b2e]">
              <span className="text-sm text-slate-500 dark:text-slate-400">DeepSeek API</span>
              <Badge tone={deepSeekConfigured ? "good" : "warn"}>{deepSeekConfigured ? "已配置" : "未配置"}</Badge>
            </div>
          </div>
        </SectionCard>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
          <StatCard label="历史实验" value={experiments.length} hint="保存在 SQLite，不保存原始文件" tone="info" />
          <StatCard label="模型注册表" value={modelSummary} hint="未安装模型会显示原因和安装命令" tone="good" />
        </div>

        <SectionCard title="最近实验" description={latest ? "继续查看最近一次分析结果。" : "运行一次实验后，这里会出现最近记录。"}>
          {latest ? (
            <div>
              <div className="text-sm font-semibold text-slate-950 dark:text-white">{latest.experimentName}</div>
              <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {latest.fileName} / {latest.targetColumn} / 推荐模型 {latest.recommendedModelId ?? "暂无"}
              </p>
              <Link className={`${controls.secondaryButton} mt-4 w-full`} to={`/experiments/${latest.experimentId}`}>
                打开实验详情
              </Link>
            </div>
          ) : (
            <Link className={`${controls.secondaryButton} w-full`} to="/upload">
              上传数据开始
            </Link>
          )}
        </SectionCard>
      </aside>
    </div>
  );
}
