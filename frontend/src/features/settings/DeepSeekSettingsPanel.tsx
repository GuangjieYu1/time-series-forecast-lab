import { useEffect, useState } from "react";
import { testDeepSeekConnection } from "../../shared/api/client";
import { clearDeepSeekSettings, defaultDeepSeekSettings, loadDeepSeekSettings, saveDeepSeekSettings } from "../../shared/api/deepseekSettings";
import { ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, SectionCard, surface } from "../../shared/components/Ui";
import type { DeepSeekSettings } from "../../shared/types/api";

type ConnectionState = "not_configured" | "testing" | "success" | "failed";

function stateText(state: ConnectionState) {
  return {
    not_configured: "未配置",
    testing: "测试中",
    success: "连接成功",
    failed: "连接失败"
  }[state];
}

function stateTone(state: ConnectionState) {
  return state === "success" ? "good" : state === "failed" ? "bad" : state === "testing" ? "info" : "neutral";
}

export function DeepSeekSettingsPanel() {
  const [settings, setSettings] = useState<DeepSeekSettings>(defaultDeepSeekSettings);
  const [showKey, setShowKey] = useState(false);
  const [state, setState] = useState<ConnectionState>("not_configured");
  const [message, setMessage] = useState("请输入 DeepSeek API Key。");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loaded = loadDeepSeekSettings();
    setSettings(loaded);
    setState("not_configured");
    setMessage(loaded.apiKey ? "已读取当前浏览器中的配置，可以测试连接。" : "请输入 DeepSeek API Key。");
  }, []);

  function update<K extends keyof DeepSeekSettings>(key: K, value: DeepSeekSettings[K]) {
    setSettings((current) => ({ ...current, [key]: value }));
  }

  async function testConnection() {
    setError(null);
    if (!settings.apiKey.trim()) {
      setState("failed");
      setMessage("请先输入 API Key。");
      return;
    }
    setState("testing");
    setMessage("正在测试 DeepSeek 连接...");
    try {
      const response = await testDeepSeekConnection({
        apiKey: settings.apiKey.trim(),
        baseUrl: settings.baseUrl.trim(),
        model: settings.model.trim()
      });
      setState(response.success ? "success" : "failed");
      setMessage(response.message);
    } catch (err) {
      setState("failed");
      setError(err instanceof Error ? err.message : "连接测试失败。");
    }
  }

  function save() {
    saveDeepSeekSettings(settings);
    setMessage(settings.rememberLocal ? "设置已保存到本机浏览器 localStorage。" : "设置已保存到当前浏览器会话。");
  }

  function clear() {
    clearDeepSeekSettings();
    setSettings(defaultDeepSeekSettings);
    setState("not_configured");
    setMessage("已清除当前浏览器中的 DeepSeek 设置。");
  }

  return (
    <SectionCard
      title="DeepSeek 报告配置"
      description="API Key 只在测试连接和生成报告时临时发送到后端，不写入 SQLite，不写入实验历史。"
      action={<Badge tone={stateTone(state)}>{stateText(state)}</Badge>}
      className="relative overflow-hidden"
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-r from-indigo-500/10 via-cyan-400/10 to-transparent" />
      <div className="relative">
        <ErrorBanner message={error} />
        {state === "testing" ? <LoadingBlock label="正在测试 DeepSeek 连接..." /> : null}

        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 md:col-span-2">
            <span className={`text-sm font-medium ${surface.strongText}`}>API Key</span>
            <div className="flex gap-2">
              <input
                className={controls.input}
                type={showKey ? "text" : "password"}
                placeholder="sk-..."
                value={settings.apiKey}
                onChange={(event) => update("apiKey", event.target.value)}
              />
              <button className={controls.secondaryButton} type="button" onClick={() => setShowKey((value) => !value)}>
                {showKey ? "隐藏" : "显示"}
              </button>
            </div>
          </label>

          <label className="space-y-2">
            <span className={`text-sm font-medium ${surface.strongText}`}>Base URL</span>
            <input className={controls.input} value={settings.baseUrl} onChange={(event) => update("baseUrl", event.target.value)} />
          </label>

          <label className="space-y-2">
            <span className={`text-sm font-medium ${surface.strongText}`}>模型</span>
            <select className={controls.input} value={settings.model} onChange={(event) => update("model", event.target.value)}>
              <option value="deepseek-v4-flash">deepseek-v4-flash</option>
              <option value="deepseek-chat">deepseek-chat</option>
              <option value="deepseek-reasoner">deepseek-reasoner</option>
            </select>
          </label>
        </div>

        <label className="mt-4 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
          <input
            className="mt-1"
            type="checkbox"
            checked={settings.rememberLocal}
            onChange={(event) => update("rememberLocal", event.target.checked)}
          />
          <span>仅在你自己的电脑上使用“本机记住”。API Key 会保存在当前浏览器本地存储中，不会上传到历史记录。</span>
        </label>

        <div className="mt-5 flex flex-wrap gap-3">
          <button className={controls.primaryButton} type="button" onClick={() => void testConnection()}>
            测试连接
          </button>
          <button className={controls.secondaryButton} type="button" onClick={save}>
            保存设置
          </button>
          <button className={controls.dangerButton} type="button" onClick={clear}>
            清除设置
          </button>
        </div>

        <p className={`mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 dark:border-white/10 dark:bg-[#0b1020] ${surface.mutedText}`}>
          {message}
        </p>
      </div>
    </SectionCard>
  );
}
