import type { DeepSeekSettings } from "../types/api";

const STORAGE_KEY = "time_series_forecast_lab_deepseek";

export const defaultDeepSeekSettings: DeepSeekSettings = {
  apiKey: "",
  baseUrl: "https://api.deepseek.com",
  model: "deepseek-v4-flash",
  rememberLocal: false
};

export function loadDeepSeekSettings(): DeepSeekSettings {
  if (typeof window === "undefined") return defaultDeepSeekSettings;
  const local = window.localStorage.getItem(STORAGE_KEY);
  const session = window.sessionStorage.getItem(STORAGE_KEY);
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
  const payload = JSON.stringify(settings);
  if (settings.rememberLocal) {
    window.localStorage.setItem(STORAGE_KEY, payload);
    window.sessionStorage.removeItem(STORAGE_KEY);
  } else {
    window.sessionStorage.setItem(STORAGE_KEY, payload);
    window.localStorage.removeItem(STORAGE_KEY);
  }
}

export function clearDeepSeekSettings(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
  window.sessionStorage.removeItem(STORAGE_KEY);
}
