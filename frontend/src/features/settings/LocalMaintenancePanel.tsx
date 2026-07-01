import { useState } from "react";
import { triggerLocalRebuild } from "../../shared/api/client";
import { ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, SectionCard, surface } from "../../shared/components/Ui";

export function LocalMaintenancePanel() {
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("本机 localhost 环境下可一键重建并重启前后端；如果后端已经完全无响应，请直接双击 deploy 目录下脚本。");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setLoading(true);
    setError(null);
    setMessage("正在提交本地重建请求，当前页面可能会在几秒后暂时断开。");
    try {
      const response = await triggerLocalRebuild(password);
      setMessage(`${response.message}${response.logPath ? ` 日志：${response.logPath}` : ""}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交本地重建请求失败。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <SectionCard
      title="本地一键重建 / 重启"
      description="这个入口只给本机 localhost 用。它会重新安装依赖、重新构建前端，并重启 8100 / 5173 服务。"
      action={<Badge tone="warn">本机维护</Badge>}
      className="relative overflow-hidden"
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-r from-amber-500/10 via-cyan-400/10 to-transparent" />
      <div className="relative">
        <ErrorBanner message={error} />
        {loading ? <LoadingBlock label="正在安排本地重建，请稍候..." /> : null}

        <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
          <label className="space-y-2">
            <span className={`text-sm font-medium ${surface.strongText}`}>本地维护密码</span>
            <input
              className={controls.input}
              type={showPassword ? "text" : "password"}
              placeholder="请输入本地维护密码"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button className={controls.secondaryButton} type="button" onClick={() => setShowPassword((value) => !value)}>
            {showPassword ? "隐藏密码" : "显示密码"}
          </button>
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <button className={controls.primaryButton} type="button" disabled={loading || !password.trim()} onClick={() => void submit()}>
            一键重建并重启本地服务
          </button>
        </div>

        <div className={`mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 dark:border-white/10 dark:bg-[#0b1020] ${surface.mutedText}`}>
          {message}
        </div>

        <div className="mt-4 rounded-2xl border border-cyan-200 bg-cyan-50 p-4 text-sm leading-6 text-cyan-800 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100">
          如果你已经是本地部署并且后端彻底卡死，直接双击以下脚本即可：
          <div className="mt-2 font-mono text-xs leading-6">
            <div>macOS / Linux：deploy/local-rebuild.command</div>
            <div>Windows：deploy/local-rebuild.bat</div>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
