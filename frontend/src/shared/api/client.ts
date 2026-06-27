import type {
  DeepSeekConnectionResponse,
  DeepSeekSettings,
  DeviceInfo,
  ExperimentDetail,
  ExperimentListItem,
  FinalForecastResponse,
  ForecastProgress,
  ForecastRunRequest,
  ForecastRunResponse,
  ModelCapability,
  ReportOptions,
  ReportResponse,
  SheetPreview,
  UploadPreviewResponse
} from "../types/api";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      message = body?.message ?? body?.detail?.message ?? message;
    } catch {
      // ignore non-json error bodies
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function uploadPreview(file: File): Promise<UploadPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  return parseResponse<UploadPreviewResponse>(
    await fetch("/api/upload/preview", {
      method: "POST",
      body: form
    })
  );
}

export async function fetchSheetPreview(uploadId: string, sheetName: string): Promise<SheetPreview> {
  return parseResponse<SheetPreview>(await fetch(`/api/upload/${uploadId}/sheets/${encodeURIComponent(sheetName)}/preview?limit=100`));
}

export async function fetchModels(): Promise<ModelCapability[]> {
  const body = await parseResponse<{ models: ModelCapability[] }>(await fetch("/api/models"));
  return body.models;
}

export async function fetchDevice(): Promise<string> {
  const body = await parseResponse<Partial<DeviceInfo> & { device: string }>(await fetch("/api/models/device"));
  return body.device;
}

export async function fetchDeviceInfo(): Promise<DeviceInfo> {
  const body = await parseResponse<Partial<DeviceInfo> & { device: string }>(await fetch("/api/models/device"));
  return {
    device: body.device,
    memoryTotalMb: body.memoryTotalMb ?? null,
    memoryAvailableMb: body.memoryAvailableMb ?? null
  };
}

export async function fetchHealth(): Promise<{ ok: boolean; app: string; version?: string }> {
  return parseResponse<{ ok: boolean; app: string; version?: string }>(await fetch("/api/health"));
}

export async function runForecast(request: ForecastRunRequest): Promise<ForecastRunResponse> {
  return parseResponse<ForecastRunResponse>(
    await fetch("/api/forecast/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    })
  );
}

export function createRunId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `run_${crypto.randomUUID()}`;
  }
  return `run_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function subscribeForecastProgress(
  runId: string,
  onProgress: (progress: ForecastProgress) => void
): () => void {
  const source = new EventSource(`/api/forecast/progress/${encodeURIComponent(runId)}/events`);
  source.onmessage = (event) => {
    const progress = JSON.parse(event.data) as ForecastProgress;
    onProgress(progress);
    if (progress.status === "completed" || progress.status === "failed") {
      source.close();
    }
  };
  return () => source.close();
}

export async function runFinalForecast(experimentId: string, finalModelId: string, horizon: number, runId?: string): Promise<FinalForecastResponse> {
  return parseResponse<FinalForecastResponse>(
    await fetch("/api/forecast/final", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experimentId, finalModelId, horizon, runId })
    })
  );
}

export async function fetchExperiments(): Promise<ExperimentListItem[]> {
  return parseResponse<ExperimentListItem[]>(await fetch("/api/experiments"));
}

export async function fetchExperiment(experimentId: string): Promise<ExperimentDetail> {
  return parseResponse<ExperimentDetail>(await fetch(`/api/experiments/${experimentId}`));
}

export async function deleteExperiment(experimentId: string): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(`/api/experiments/${experimentId}`, {
      method: "DELETE"
    })
  );
}

export async function testDeepSeekConnection(settings: Pick<DeepSeekSettings, "apiKey" | "baseUrl" | "model">): Promise<DeepSeekConnectionResponse> {
  return parseResponse<DeepSeekConnectionResponse>(
    await fetch("/api/llm/deepseek/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
    })
  );
}

export async function generateReport(
  experimentId: string,
  settings: Pick<DeepSeekSettings, "apiKey" | "baseUrl" | "model">,
  reportOptions: ReportOptions
): Promise<ReportResponse> {
  return parseResponse<ReportResponse>(
    await fetch("/api/reports/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experimentId, ...settings, reportOptions })
    })
  );
}
