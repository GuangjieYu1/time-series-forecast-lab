import type { DeepSeekSettings } from "../types/api";
import { getCurrentAuthUserId } from "./workspaceSession";

function storageKey() {
  const userId = getCurrentAuthUserId();
  return `time_series_forecast_lab_deepseek:${userId ?? "anonymous"}`;
}

export const defaultDeepSeekSettings: DeepSeekSettings = {
  apiKey: "",
  baseUrl: "https://api.deepseek.com",
  model: "deepseek-v4-flash",
  rememberLocal: false
};

export function loadDeepSeekSettings(): DeepSeekSettings {
  if (typeof window === "undefined") return defaultDeepSeekSettings;
  const key = storageKey();
  const local = window.localStorage.getItem(key);
  const session = window.sessionStorage.getItem(key);
  const raw = local ?? session;
  if (!raw) return defaultDeepSeekSettings;
  try {
    return { ...defaultDeepSeekSettings, ...JSON.parse(raw), rememberLocal: Boolean(local) };
  } catch {
    return defaultDeepSeekSettings;
  }
}

export function saveDeepSeekSettings(settings: DeepSeekSettings): void {
  if (typeof window === "undefined") return;
  const key = storageKey();
  const payload = JSON.stringify(settings);
  if (settings.rememberLocal) {
    window.localStorage.setItem(key, payload);
    window.sessionStorage.removeItem(key);
  } else {
    window.sessionStorage.setItem(key, payload);
    window.localStorage.removeItem(key);
  }
}

export function clearDeepSeekSettings(): void {
  if (typeof window === "undefined") return;
  const key = storageKey();
  window.localStorage.removeItem(key);
  window.sessionStorage.removeItem(key);
}
