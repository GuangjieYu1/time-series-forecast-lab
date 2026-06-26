import { useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ExperimentDetailPage } from "../features/experiments/ExperimentDetailPage";
import { ExperimentsPage } from "../features/experiments/ExperimentsPage";
import { ForecastPage } from "../features/forecast/ForecastPage";
import { ModelsPage } from "../features/models/ModelsPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { ApiSettingsPage } from "../features/settings/ApiSettingsPage";
import { UploadPage } from "../features/upload/UploadPage";
import { fetchDevice, fetchHealth, fetchModels } from "../shared/api/client";
import { loadDeepSeekSettings } from "../shared/api/deepseekSettings";
import { Badge, controls, surface } from "../shared/components/Ui";
import { zhCN } from "../shared/i18n/zhCN";
import { useLabStore } from "./store";

const navItems = [
  { to: "/", label: zhCN.nav.overview, code: "OV" },
  { to: "/upload", label: zhCN.nav.upload, code: "UP" },
  { to: "/forecast", label: zhCN.nav.forecast, code: "FX" },
  { to: "/models", label: zhCN.nav.models, code: "MD" },
  { to: "/experiments", label: zhCN.nav.experiments, code: "HX" },
  { to: "/settings", label: zhCN.nav.settings, code: "AI" }
];

function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button className={controls.secondaryButton} onClick={onToggle}>
      {dark ? "浅色模式" : "深色模式"}
    </button>
  );
}

function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-72 border-r border-white/10 bg-[#0b1020] p-4 text-slate-200 lg:block">
      <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-400 to-cyan-300 text-sm font-black text-[#080b14]">
            TS
          </div>
          <div>
            <div className="text-base font-semibold text-white">{zhCN.productName}</div>
            <div className="text-xs text-slate-400">{zhCN.productNameEn}</div>
          </div>
        </div>
      </div>

      <nav className="mt-6 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `group flex items-center gap-3 rounded-2xl px-3 py-3 text-sm font-medium transition ${
                isActive
                  ? "bg-white text-[#080b14] shadow-[0_16px_45px_rgba(255,255,255,0.12)]"
                  : "text-slate-400 hover:bg-white/8 hover:text-white"
              }`
            }
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-current/15 text-[11px] font-bold">{item.code}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="absolute bottom-4 left-4 right-4 overflow-hidden rounded-3xl border border-white/10 bg-white/[0.04] p-4">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/70 to-transparent" />
        <div className="text-xs font-semibold text-slate-200">本地 AI 数据分析工作台</div>
        <p className="mt-2 text-xs leading-5 text-slate-400">多模型回测、残差诊断、最终预测和 DeepSeek 中文报告统一在本机完成。</p>
      </div>
    </aside>
  );
}

function TopStatusBar({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  const location = useLocation();
  const { forecastResult } = useLabStore();
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [device, setDevice] = useState("检测中");
  const [timesfmStatus, setTimesfmStatus] = useState("检测中");
  const [deepSeekConfigured, setDeepSeekConfigured] = useState(false);

  useEffect(() => {
    void fetchHealth()
      .then((health) => setBackendOk(health.ok))
      .catch(() => setBackendOk(false));
    void fetchDevice().then(setDevice).catch(() => setDevice("未知"));
    void fetchModels()
      .then((models) => {
        const timesfm = models.find((model) => model.id === "timesfm");
        setTimesfmStatus(timesfm?.installStatus === "downloading" ? "需要下载" : timesfm?.installStatus ?? "未注册");
      })
      .catch(() => setTimesfmStatus("未知"));
    setDeepSeekConfigured(Boolean(loadDeepSeekSettings().apiKey));
  }, [location.pathname]);

  const pageTitle = useMemo(
    () => navItems.find((item) => (item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)))?.label ?? "实验详情",
    [location.pathname]
  );

  return (
    <header className="sticky top-0 z-10 px-4 py-4 backdrop-blur-2xl lg:pl-80">
      <div className={`${surface.glass} px-4 py-3`}>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-xs font-medium text-slate-400">当前页面</div>
            <div className="text-lg font-semibold text-white">{pageTitle}</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={backendOk ? "good" : backendOk === false ? "bad" : "warn"}>
              后端：{backendOk ? "在线" : backendOk === false ? "离线" : "检测中"}
            </Badge>
            <Badge tone="info">设备：{device}</Badge>
            <Badge tone={timesfmStatus === "available" ? "good" : timesfmStatus === "需要下载" ? "warn" : "neutral"}>TimesFM：{timesfmStatus}</Badge>
            <Badge tone={deepSeekConfigured ? "good" : "warn"}>DeepSeek：{deepSeekConfigured ? "已配置" : "未配置"}</Badge>
            <Badge tone="neutral">实验：{forecastResult?.experimentId ?? "尚未运行"}</Badge>
            <ThemeToggle dark={dark} onToggle={onToggle} />
          </div>
        </div>
      </div>
    </header>
  );
}

export function App() {
  const [dark, setDark] = useState(() => window.localStorage.getItem("tsfl_theme") !== "light");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    window.localStorage.setItem("tsfl_theme", dark ? "dark" : "light");
  }, [dark]);

  return (
    <div className={dark ? surface.shell : surface.page}>
      <Sidebar />
      <TopStatusBar dark={dark} onToggle={() => setDark((value) => !value)} />
      <main className="px-4 pb-8 pt-2 lg:pl-80">
        <div className="mx-auto max-w-[1500px] space-y-6">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/forecast" element={<ForecastPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/experiments" element={<ExperimentsPage />} />
            <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
            <Route path="/settings" element={<ApiSettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
