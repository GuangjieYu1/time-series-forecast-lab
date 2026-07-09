import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AttributionLabPage } from "../features/attribution/AttributionLabPage";
import { ExperimentDetailPage } from "../features/experiments/ExperimentDetailPage";
import { ExperimentsPage } from "../features/experiments/ExperimentsPage";
import { FeedbackPage } from "../features/feedback/FeedbackPage";
import { ForecastPage } from "../features/forecast/ForecastPage";
import { ModelsPage } from "../features/models/ModelsPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { ApiSettingsPage } from "../features/settings/ApiSettingsPage";
import { UploadPage } from "../features/upload/UploadPage";
import { bootstrapAuth, checkUsernameAvailability, fetchDevice, fetchHealth, fetchModels, fetchSession, login, logout, register } from "../shared/api/client";
import { loadDeepSeekSettings } from "../shared/api/deepseekSettings";
import { ErrorBanner, LoadingBlock } from "../shared/components/Status";
import { Badge, controls, surface } from "../shared/components/Ui";
import { zhCN } from "../shared/i18n/zhCN";
import type { AuthSessionResponse, WorkspaceSummary } from "../shared/types/api";
import { useLabStore } from "./store";

const navItems = [
  { to: "/", label: zhCN.nav.overview, code: "OV" },
  { to: "/upload", label: zhCN.nav.upload, code: "UP" },
  { to: "/forecast", label: zhCN.nav.forecast, code: "FX" },
  { to: "/models", label: zhCN.nav.models, code: "MD" },
  { to: "/experiments", label: zhCN.nav.experiments, code: "HX" },
  { to: "/feedback", label: zhCN.nav.feedback, code: "FB" },
  { to: "/settings", label: zhCN.nav.settings, code: "AI" }
];

function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button className={`${controls.secondaryButton} shrink-0`} onClick={onToggle} aria-label={dark ? "切换到浅色模式" : "切换到深色模式"}>
      <span className="text-base sm:hidden" aria-hidden="true">{dark ? "☀" : "☾"}</span>
      <span className="hidden sm:inline">{dark ? "浅色模式" : "深色模式"}</span>
    </button>
  );
}

function NavigationPanel({ mobile = false, onNavigate }: { mobile?: boolean; onNavigate?: () => void }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-400 to-cyan-300 text-sm font-black text-[#080b14]">
            TS
          </div>
          <div>
            <div className="text-base font-semibold text-white">{zhCN.productName}</div>
            <div className="text-xs text-slate-400">{zhCN.productNameEn}</div>
          </div>
          {mobile ? (
            <button
              type="button"
              className="ml-auto flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 text-2xl text-slate-300 transition hover:bg-white/10 hover:text-white"
              onClick={onNavigate}
              aria-label="关闭导航"
            >
              ×
            </button>
          ) : null}
        </div>
      </div>

      <nav className="mt-6 min-h-0 flex-1 space-y-1 overflow-y-auto" aria-label="主导航">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              `group flex min-h-12 items-center gap-3 rounded-2xl px-3 py-3 text-sm font-medium transition ${
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

      <div className="relative mt-5 shrink-0 overflow-hidden rounded-3xl border border-white/10 bg-white/[0.04] p-4">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/70 to-transparent" />
        <div className="text-xs font-semibold text-slate-200">本地 AI 数据分析工作台</div>
        <p className="mt-2 text-xs leading-5 text-slate-400">现在支持本地多用户与工作区切换，实验、报告、上传和回放都按当前空间隔离。</p>
      </div>
    </div>
  );
}

function Sidebar({ mobileOpen, onMobileClose }: { mobileOpen: boolean; onMobileClose: () => void }) {
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-72 border-r border-white/10 bg-[#0b1020] p-4 text-slate-200 lg:block">
        <NavigationPanel />
      </aside>

      <div
        className={`fixed inset-0 z-40 transition lg:hidden ${mobileOpen ? "pointer-events-auto" : "pointer-events-none"}`}
        aria-hidden={!mobileOpen}
      >
        <button
          type="button"
          className={`absolute inset-0 bg-slate-950/70 backdrop-blur-sm transition-opacity ${mobileOpen ? "opacity-100" : "opacity-0"}`}
          onClick={onMobileClose}
          aria-label="关闭导航遮罩"
          tabIndex={mobileOpen ? 0 : -1}
        />
        <aside
          id="mobile-navigation"
          className={`absolute inset-y-0 left-0 w-[min(88vw,340px)] border-r border-white/10 bg-[#0b1020] p-4 text-slate-200 shadow-2xl transition-transform duration-300 ${
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          aria-label="移动端导航"
        >
          <NavigationPanel mobile onNavigate={onMobileClose} />
        </aside>
      </div>
    </>
  );
}

function MobileMenuButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-2xl text-white transition hover:bg-white/10 lg:hidden"
      onClick={onClick}
      aria-label={open ? "关闭主导航" : "打开主导航"}
      aria-expanded={open}
      aria-controls="mobile-navigation"
    >
      {open ? "×" : "☰"}
    </button>
  );
}

function WorkspaceBadge({ workspace }: { workspace: WorkspaceSummary | null }) {
  if (!workspace) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={workspace.kind === "example" ? "warn" : workspace.kind === "shared" ? "info" : "good"}>{workspace.name}</Badge>
      <Badge tone="neutral">{workspace.kind === "personal" ? "Personal" : workspace.kind === "shared" ? "Shared" : "Example"}</Badge>
      <Badge tone="neutral">{workspace.role === "owner" ? "Owner" : "Member"}</Badge>
      {workspace.isReadOnly ? <Badge tone="warn">只读</Badge> : null}
    </div>
  );
}

function TopStatusBar({
  dark,
  onToggle,
  mobileOpen,
  onMenuToggle,
  onWorkspaceChange,
  onLogout,
}: {
  dark: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMenuToggle: () => void;
  onWorkspaceChange: (workspaceId: string) => void;
  onLogout: () => Promise<void>;
}) {
  const location = useLocation();
  const { forecastResult, workspaces, selectedWorkspaceId, currentUser } = useLabStore();
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [device, setDevice] = useState("检测中");
  const [timesfmStatus, setTimesfmStatus] = useState("检测中");
  const [deepSeekConfigured, setDeepSeekConfigured] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const selectedWorkspace = workspaces.find((item) => item.workspaceId === selectedWorkspaceId) ?? null;

  useEffect(() => {
    void fetchHealth()
      .then((health) => setBackendOk(health.ok))
      .catch(() => setBackendOk(false));
    void fetchDevice().then(setDevice).catch(() => setDevice("未知"));
    void fetchModels()
      .then((models) => {
        const timesfm = models.find((model) => model.id === "timesfm");
        setTimesfmStatus(timesfm?.installStatus === "downloading" ? "下载中" : timesfm?.installStatus ?? "未注册");
      })
      .catch(() => setTimesfmStatus("未知"));
    setDeepSeekConfigured(Boolean(loadDeepSeekSettings().apiKey));
  }, [location.pathname, currentUser?.userId]);

  const pageTitle = useMemo(
    () => navItems.find((item) => (item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)))?.label ?? "实验详情",
    [location.pathname]
  );

  async function handleLogoutClick() {
    try {
      setLoggingOut(true);
      await onLogout();
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <header className="sticky top-0 z-30 px-3 py-3 backdrop-blur-2xl sm:px-4 sm:py-4 lg:ml-72 lg:px-6">
      <div className={`${surface.glass} flex flex-col gap-3 px-3 py-3 sm:px-4`}>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 items-center gap-3 xl:flex-1">
            <MobileMenuButton open={mobileOpen} onClick={onMenuToggle} />
            <div className="min-w-0">
              <div className="text-xs font-medium text-slate-400">当前页面</div>
              <div className="truncate text-base font-semibold text-white sm:text-lg">{pageTitle}</div>
            </div>
            <div className="ml-auto sm:hidden">
              <ThemeToggle dark={dark} onToggle={onToggle} />
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-[minmax(0,280px)_auto] xl:min-w-[520px]">
            <label className="flex min-w-0 flex-col gap-1">
              <span className="text-xs font-medium text-slate-400">当前工作区</span>
              <select
                className={`${controls.input} min-w-0 border-white/10 bg-white/10 text-white`}
                value={selectedWorkspaceId ?? ""}
                onChange={(event) => onWorkspaceChange(event.target.value)}
              >
                {workspaces.map((workspace) => (
                  <option key={workspace.workspaceId} value={workspace.workspaceId} className="text-slate-950">
                    {workspace.name} · {workspace.kind} · {workspace.role}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex flex-wrap items-end gap-2 sm:justify-end">
              <div className="min-w-0 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-right">
                <div className="truncate text-sm font-semibold text-white">{currentUser?.displayName ?? "未登录"}</div>
                <div className="truncate text-xs text-slate-400">
                  @{currentUser?.username}
                  {currentUser?.isAdmin ? " · Admin" : ""}
                </div>
              </div>
              <button className={controls.secondaryButton} onClick={handleLogoutClick} disabled={loggingOut}>
                {loggingOut ? "退出中..." : "退出登录"}
              </button>
              <div className="hidden sm:block">
                <ThemeToggle dark={dark} onToggle={onToggle} />
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <WorkspaceBadge workspace={selectedWorkspace} />
          <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1 xl:justify-end">
            <Badge tone={backendOk ? "good" : backendOk === false ? "bad" : "warn"}>
              后端：{backendOk ? "在线" : backendOk === false ? "离线" : "检测中"}
            </Badge>
            <Badge tone="info">设备：{device}</Badge>
            <Badge tone={timesfmStatus === "available" ? "good" : timesfmStatus === "not_installed" ? "warn" : "neutral"}>TimesFM：{timesfmStatus}</Badge>
            <Badge tone={deepSeekConfigured ? "good" : "warn"}>DeepSeek：{deepSeekConfigured ? "已配置" : "未配置"}</Badge>
            <Badge tone="neutral">实验：{forecastResult?.experimentId ?? "尚未运行"}</Badge>
          </div>
        </div>
      </div>
    </header>
  );
}

function AuthField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  onBlur,
  helper,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password";
  placeholder?: string;
  onBlur?: () => void;
  helper?: ReactNode;
}) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium text-slate-200">{label}</span>
      <input
        className={`${controls.input} border-white/10 bg-white/10 text-white placeholder:text-slate-500`}
        value={value}
        type={type}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
      />
      {helper ? <div className="text-xs leading-5 text-slate-400">{helper}</div> : null}
    </label>
  );
}

type AuthMode = "login" | "register" | "register_success";
type UsernameAvailabilityState = "idle" | "checking" | "available" | "taken" | "invalid";

function normalizeUsername(username: string) {
  return username.trim();
}

function isRegisterUsernameValid(username: string) {
  const normalized = normalizeUsername(username);
  return normalized.length >= 3 && normalized.length <= 120;
}

function passwordMeetsRegisterRule(password: string) {
  return password.length >= 8 && /[A-Za-z]/.test(password) && /\d/.test(password);
}

function getPasswordStrength(password: string): { label: "弱" | "中" | "强"; className: string } {
  let score = 0;
  if (password.length >= 8) score += 1;
  if (/[A-Za-z]/.test(password) && /\d/.test(password)) score += 1;
  if (password.length >= 12) score += 1;
  if ((/[A-Z]/.test(password) && /[a-z]/.test(password)) || /[^A-Za-z0-9]/.test(password)) score += 1;
  if (score >= 4) return { label: "强", className: "text-emerald-300" };
  if (score >= 2) return { label: "中", className: "text-amber-300" };
  return { label: "弱", className: "text-rose-300" };
}

function AuthScreen({
  bootstrapRequired,
  submitting,
  error,
  onResolved,
}: {
  bootstrapRequired: boolean;
  submitting: boolean;
  error: string | null;
  onResolved: (session: AuthSessionResponse) => void;
}) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [localSubmitting, setLocalSubmitting] = useState(false);
  const [mode, setMode] = useState<AuthMode>("login");
  const [pendingRegisterSession, setPendingRegisterSession] = useState<AuthSessionResponse | null>(null);
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [usernameAvailability, setUsernameAvailability] = useState<UsernameAvailabilityState>("idle");
  const [usernameAvailabilityMessage, setUsernameAvailabilityMessage] = useState<string | null>(null);
  const [lastCheckedUsername, setLastCheckedUsername] = useState("");
  const [touched, setTouched] = useState({ username: false, displayName: false, password: false });
  const usernameCheckRequestRef = useRef(0);
  const canRegister = !bootstrapRequired;
  const isRegistering = canRegister && mode === "register";
  const isRegisterSuccess = canRegister && mode === "register_success";
  const normalizedUsername = normalizeUsername(username);
  const usernameLocallyValid = isRegisterUsernameValid(username);
  const displayNameValid = displayName.trim().length > 0;
  const passwordRegisterValid = passwordMeetsRegisterRule(password);
  const passwordStrength = getPasswordStrength(password);

  function resetRegisterValidationState() {
    setPendingRegisterSession(null);
    setSubmitAttempted(false);
    setUsernameAvailability("idle");
    setUsernameAvailabilityMessage(null);
    setLastCheckedUsername("");
    setTouched({ username: false, displayName: false, password: false });
  }

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setLocalError(null);
    if (nextMode !== "register") {
      resetRegisterValidationState();
    }
  }

  function markTouched(field: "username" | "displayName" | "password") {
    setTouched((current) => ({ ...current, [field]: true }));
  }

  async function handleRegisterUsernameBlur() {
    markTouched("username");
    if (!isRegistering) return;
    setUsernameAvailabilityMessage(null);
    if (!normalizedUsername) {
      setUsernameAvailability("idle");
      setLastCheckedUsername("");
      return;
    }
    if (!usernameLocallyValid) {
      setUsernameAvailability("invalid");
      setLastCheckedUsername("");
      return;
    }
    if (lastCheckedUsername === normalizedUsername) {
      return;
    }
    const requestId = usernameCheckRequestRef.current + 1;
    usernameCheckRequestRef.current = requestId;
    setUsernameAvailability("checking");
    try {
      const result = await checkUsernameAvailability(normalizedUsername);
      if (usernameCheckRequestRef.current !== requestId) return;
      setUsernameAvailability(result.reason);
      setUsernameAvailabilityMessage(result.message);
      setLastCheckedUsername(result.normalizedUsername);
    } catch {
      if (usernameCheckRequestRef.current !== requestId) return;
      setUsernameAvailability("idle");
      setUsernameAvailabilityMessage("暂时无法检查用户名是否可用，你可以稍后再试。");
      setLastCheckedUsername("");
    }
  }

  function usernameHelper() {
    if (!isRegistering) return null;
    const shouldShowValidation = touched.username || submitAttempted || username.length > 0;
    if (!shouldShowValidation) {
      return <span>用户名长度通过后，失焦时会自动查重。</span>;
    }
    if (!normalizedUsername || !usernameLocallyValid) {
      return <span className="text-rose-300">用户名需为 3-120 个字符。</span>;
    }
    if (usernameAvailability === "checking") {
      return <span className="text-cyan-300">正在检查用户名是否可用…</span>;
    }
    if (usernameAvailability === "available") {
      return <span className="text-emerald-300">用户名可用。</span>;
    }
    if (usernameAvailability === "taken") {
      return <span className="text-rose-300">{usernameAvailabilityMessage ?? "用户名已被占用。"}</span>;
    }
    if (usernameAvailability === "invalid") {
      return <span className="text-rose-300">{usernameAvailabilityMessage ?? "用户名需为 3-120 个字符。"}</span>;
    }
    if (usernameAvailabilityMessage) {
      return <span className="text-amber-300">{usernameAvailabilityMessage}</span>;
    }
    return <span>失焦后会自动检查这个用户名是否可用。</span>;
  }

  function displayNameHelper() {
    if (!(bootstrapRequired || isRegistering)) return null;
    if ((touched.displayName || submitAttempted) && !displayNameValid) {
      return <span className="text-rose-300">显示名称不能为空。</span>;
    }
    return <span>显示名称会用于你的 Personal Workspace 名称。</span>;
  }

  function passwordHelper() {
    if (!isRegistering) return null;
    return (
      <div className="space-y-1">
        <div className={(touched.password || submitAttempted) && !passwordRegisterValid ? "text-rose-300" : "text-slate-400"}>
          密码规则：至少 8 位，且同时包含字母和数字。
        </div>
        <div className={passwordStrength.className}>密码强度：{passwordStrength.label}</div>
      </div>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    setSubmitAttempted(true);
    setLocalSubmitting(true);
    try {
      if (bootstrapRequired) {
        if (!displayNameValid) return;
        const session = await bootstrapAuth({ username, displayName, password });
        onResolved(session);
        return;
      }
      if (isRegistering) {
        if (!usernameLocallyValid || !displayNameValid || !passwordRegisterValid || usernameAvailability === "checking" || usernameAvailability === "taken" || usernameAvailability === "invalid") {
          return;
        }
        const session = await register({ username, displayName, password });
        setPendingRegisterSession(session);
        setMode("register_success");
        return;
      }
      const session = await login({ username, password });
      onResolved(session);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "认证失败。");
    } finally {
      setLocalSubmitting(false);
    }
  }

  const registerSubmitDisabled =
    submitting ||
    localSubmitting ||
    !usernameLocallyValid ||
    !displayNameValid ||
    !passwordRegisterValid ||
    usernameAvailability === "checking" ||
    usernameAvailability === "taken" ||
    usernameAvailability === "invalid";

  return (
    <div className={surface.shell}>
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col justify-center gap-8 px-4 py-10 lg:grid lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
        <div className="space-y-6">
          <div className="inline-flex items-center rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold text-cyan-100">
            Local multi-user workspace v1
          </div>
          <div className="space-y-4">
            <h1 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl">Forecast Lab</h1>
            <p className="max-w-2xl text-base leading-7 text-slate-300">
              现在实验、报告、上传、Feature Factory 和 Runtime 回放都跟随当前工作区隔离。这个版本只做本地多用户，不依赖云端账号体系。
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              ["工作区隔离", "每个用户默认拥有 Personal Workspace，也可加入 Shared Workspace。"],
              ["浏览器 API 设置", "DeepSeek / API Key 继续只保存在当前浏览器，并按 userId 做隔离。"],
              ["只读 Example", "系统初始化后会自动附带 1 个 walkthrough Example Workspace。"]
            ].map(([title, detail]) => (
              <div key={title} className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
                <div className="text-sm font-semibold text-white">{title}</div>
                <div className="mt-2 text-sm leading-6 text-slate-400">{detail}</div>
              </div>
            ))}
          </div>
        </div>

        <div className={`${surface.workbench} p-6 sm:p-8`}>
          <div className="mb-6">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-300">
              {bootstrapRequired ? "Bootstrap" : isRegisterSuccess ? "Success" : isRegistering ? "Register" : "Login"}
            </div>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
              {bootstrapRequired ? "创建第一个管理员账号" : isRegisterSuccess ? "注册成功" : isRegistering ? "注册新账号" : "登录 Forecast Lab"}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
              {bootstrapRequired
                ? "检测到当前数据库还没有任何用户。先完成 bootstrap 创建第一个管理员账号，后续普通用户即可自行注册，管理员也可以在系统内直接创建账号。"
                : isRegisterSuccess
                  ? "账号已创建，Personal Workspace 已就绪。Example Workspace 也已共享给你。"
                : isRegistering
                  ? "注册完成后会先进入成功过渡页，再由你手动进入系统。"
                  : "请输入用户名和密码进入你的 Personal Workspace，或切换到被共享给你的空间。"}
            </p>
          </div>

          <ErrorBanner message={error ?? localError} />

          {!bootstrapRequired && !isRegisterSuccess ? (
            <div className="mb-5 flex gap-2 rounded-2xl border border-slate-200 bg-slate-100 p-1 dark:border-white/10 dark:bg-white/[0.04]">
              <button
                type="button"
                className={`flex-1 rounded-xl px-3 py-2 text-sm font-medium transition ${
                  !isRegistering
                    ? "bg-white text-slate-950 shadow-sm dark:bg-white dark:text-slate-950"
                    : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                }`}
                onClick={() => switchMode("login")}
              >
                登录
              </button>
              <button
                type="button"
                className={`flex-1 rounded-xl px-3 py-2 text-sm font-medium transition ${
                  isRegistering
                    ? "bg-white text-slate-950 shadow-sm dark:bg-white dark:text-slate-950"
                    : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                }`}
                onClick={() => switchMode("register")}
              >
                注册
              </button>
            </div>
          ) : null}

          {isRegisterSuccess ? (
            <div className="space-y-5 rounded-3xl border border-emerald-400/20 bg-emerald-400/8 p-5">
              <div className="space-y-2">
                <div className="text-lg font-semibold text-white">账号已创建，Personal Workspace 已就绪</div>
                <p className="text-sm leading-6 text-slate-300">Example Workspace 也已共享给你。</p>
              </div>
              <button
                className={`${controls.primaryButton} w-full`}
                type="button"
                onClick={() => {
                  if (pendingRegisterSession) {
                    onResolved(pendingRegisterSession);
                  }
                }}
                disabled={!pendingRegisterSession}
              >
                进入系统
              </button>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <AuthField
                label="用户名"
                value={username}
                onChange={(nextValue) => {
                  setUsername(nextValue);
                  if (isRegistering && normalizeUsername(nextValue) !== lastCheckedUsername) {
                    setUsernameAvailability("idle");
                    setUsernameAvailabilityMessage(null);
                  }
                }}
                onBlur={isRegistering ? handleRegisterUsernameBlur : undefined}
                placeholder="例如 guangjieyu"
                helper={usernameHelper()}
              />
              {bootstrapRequired || isRegistering ? (
                <AuthField
                  label="显示名称"
                  value={displayName}
                  onChange={setDisplayName}
                  onBlur={() => markTouched("displayName")}
                  placeholder="例如 Guangjie Yu"
                  helper={displayNameHelper()}
                />
              ) : null}
              <AuthField
                label="密码"
                value={password}
                onChange={setPassword}
                onBlur={isRegistering ? () => markTouched("password") : undefined}
                type="password"
                placeholder="至少 8 位"
                helper={passwordHelper()}
              />
              <button
                className={`${controls.primaryButton} w-full`}
                type="submit"
                disabled={
                  bootstrapRequired
                    ? submitting || localSubmitting || !username.trim() || !password.trim() || !displayNameValid
                    : isRegistering
                      ? registerSubmitDisabled
                      : submitting || localSubmitting || !username.trim() || !password.trim()
                }
              >
                {submitting || localSubmitting ? "处理中..." : bootstrapRequired ? "创建管理员并进入系统" : isRegistering ? "注册" : "登录"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

export function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const [dark, setDark] = useState(() => window.localStorage.getItem("tsfl_theme") !== "light");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [bootstrapRequired, setBootstrapRequired] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const { currentUser, selectedWorkspaceId, workspaces, setSession, clearSession, selectWorkspace } = useLabStore();

  const refreshSession = useCallback(async () => {
    try {
      const session = await fetchSession();
      setBootstrapRequired(session.bootstrapRequired);
      if (session.authenticated && session.user) {
        setSession(session);
      } else {
        clearSession();
      }
      setAuthError(null);
      return session;
    } catch (err) {
      clearSession();
      setBootstrapRequired(false);
      setAuthError(err instanceof Error ? err.message : "会话初始化失败。");
      return null;
    }
  }, [clearSession, setSession]);

  useEffect(() => {
    void refreshSession().finally(() => setAuthReady(true));
  }, [refreshSession]);

  useEffect(() => {
    if (!authReady) return;
    if (!currentUser && location.pathname !== "/login") {
      navigate("/login", { replace: true });
      return;
    }
    if (currentUser && location.pathname === "/login") {
      navigate("/", { replace: true });
    }
  }, [authReady, currentUser, location.pathname, navigate]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    window.localStorage.setItem("tsfl_theme", dark ? "dark" : "light");
  }, [dark]);

  async function handleAuthResolved(session: AuthSessionResponse) {
    setAuthSubmitting(true);
    try {
      setSession(session);
      setBootstrapRequired(false);
      setAuthError(null);
      navigate("/", { replace: true });
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } finally {
      clearSession();
      navigate("/login", { replace: true });
    }
  }

  function handleWorkspaceChange(workspaceId: string) {
    if (!workspaceId || workspaceId === selectedWorkspaceId) return;
    selectWorkspace(workspaceId);
    if (location.pathname !== "/experiments" && location.pathname.startsWith("/experiments/")) {
      navigate("/experiments", { replace: true });
    }
  }

  if (!authReady) {
    return (
      <div className={surface.shell}>
        <div className="mx-auto flex min-h-screen max-w-xl items-center justify-center px-4">
          <LoadingBlock label="正在初始化本地多用户工作区..." />
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <AuthScreen
        bootstrapRequired={bootstrapRequired}
        submitting={authSubmitting}
        error={authError}
        onResolved={handleAuthResolved}
      />
    );
  }

  const selectedWorkspace = workspaces.find((item) => item.workspaceId === selectedWorkspaceId) ?? null;

  return (
    <div className={dark ? surface.shell : surface.page}>
      <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
      <TopStatusBar
        dark={dark}
        onToggle={() => setDark((value) => !value)}
        mobileOpen={mobileNavOpen}
        onMenuToggle={() => setMobileNavOpen((value) => !value)}
        onWorkspaceChange={handleWorkspaceChange}
        onLogout={handleLogout}
      />
      <main className="px-3 pb-8 pt-2 sm:px-4 lg:pl-80">
        <div className="mx-auto max-w-[1500px] space-y-6">
          {!selectedWorkspace ? <ErrorBanner message="当前账号没有可用工作区，请先联系管理员。" /> : null}
          {selectedWorkspace?.isReadOnly ? <Badge tone="warn">当前位于只读 Example Workspace，写操作会被阻止。</Badge> : null}
          <Routes>
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route path="/" element={<OverviewPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/forecast" element={<ForecastPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/experiments" element={<ExperimentsPage />} />
            <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
            <Route path="/experiments/:id/attribution" element={<AttributionLabPage />} />
            <Route path="/feedback" element={<FeedbackPage />} />
            <Route path="/settings" element={<ApiSettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
