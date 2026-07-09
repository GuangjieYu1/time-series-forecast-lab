import type {
  AddWorkspaceMemberRequest,
  AgentArtifact,
  AgentHistoryItem,
  AgentRunDetail,
  AgentRunEventsResponse,
  AgentRunRequest,
  AgentRunResponse,
  AuthSessionResponse,
  BootstrapRequest,
  CreateUserRequest,
  CreateUserGroupRequest,
  CreateWorkspaceRequest,
  DeepSeekConnectionResponse,
  DeepSeekSettings,
  DeviceInfo,
  ExperimentDetail,
  ExperimentExplainabilityResponse,
  FeatureFactoryResponse,
  ExperimentManifest,
  FeedbackCreateRequest,
  FeedbackItem,
  FeedbackListResponse,
  FeedbackNotifyTestResponse,
  ExperimentRerunResponse,
  ExperimentListItem,
  FinalForecastResponse,
  ForecastProgress,
  ForecastRunRequest,
  ForecastRunResponse,
  HolidayCalendarCatalog,
  LoginRequest,
  LocalRebuildResponse,
  ModelCapability,
  RegisterRequest,
  RuntimeEstimateRequest,
  RuntimeEstimateResponse,
  RuntimeEvent,
  RuntimeEventsResponse,
  RuntimeRunDetail,
  ReportPdfArtifact,
  ReportOptions,
  ReportResponse,
  SheetPreview,
  UsernameAvailabilityResponse,
  UpdateUserGroupsRequest,
  UpdateUserPasswordRequest,
  UpdateUserRequest,
  UpdateWorkspaceRequest,
  UploadPreviewResponse,
  WorkbenchIdeaAnalyzeRequest,
  WorkbenchIdeaAnalyzeResponse
} from "../types/api";
import type { UserGroupSummary, UserSummary, WorkspaceMemberResponse, WorkspaceSummary } from "../types/api";
import { loadSelectedWorkspaceId } from "./workspaceSession";

function currentWorkspaceId(): string | null {
  return loadSelectedWorkspaceId();
}

function buildWorkspaceUrl(path: string, params: Record<string, string | number | undefined> = {}): string {
  const search = new URLSearchParams();
  const workspaceId = currentWorkspaceId();
  if (workspaceId) search.set("workspaceId", workspaceId);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `${path}${path.includes("?") ? "&" : "?"}${query}` : path;
}

function buildInit(init?: RequestInit, workspaceScoped = true): RequestInit {
  const headers = new Headers(init?.headers ?? {});
  if (workspaceScoped) {
    const workspaceId = currentWorkspaceId();
    if (workspaceId) headers.set("X-Workspace-Id", workspaceId);
  }
  return { ...init, headers, credentials: "include" };
}

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

async function parseBlobResponse(response: Response): Promise<Blob> {
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
  return response.blob();
}

export async function uploadPreview(file: File): Promise<UploadPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  return parseResponse<UploadPreviewResponse>(
    await fetch("/api/upload/preview", buildInit({
      method: "POST",
      body: form
    }))
  );
}

export async function fetchSheetPreview(uploadId: string, sheetName: string): Promise<SheetPreview> {
  return parseResponse<SheetPreview>(await fetch(buildWorkspaceUrl(`/api/upload/${uploadId}/sheets/${encodeURIComponent(sheetName)}/preview`, { limit: 100 }), buildInit()));
}

export async function fetchHolidayCalendars(): Promise<HolidayCalendarCatalog> {
  return parseResponse<HolidayCalendarCatalog>(await fetch("/api/features/holiday-calendars"));
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
    memoryAvailableMb: body.memoryAvailableMb ?? null,
    accelerator: body.accelerator ?? {
      hardwareDetected: false,
      runtimeAvailable: false,
      type: null,
      name: null,
      memoryTotalMb: null,
      driverVersion: null,
      frameworkVersion: null,
      frameworkBuild: null,
      cudaRuntime: null,
      reason: null
    }
  };
}

export async function fetchHealth(): Promise<{ ok: boolean; app: string; version?: string }> {
  return parseResponse<{ ok: boolean; app: string; version?: string }>(await fetch("/api/health", buildInit(undefined, false)));
}

export async function runForecast(request: ForecastRunRequest): Promise<ForecastRunResponse> {
  return parseResponse<ForecastRunResponse>(
    await fetch("/api/forecast/run", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    }))
  );
}

export async function fetchForecastProgress(runId: string): Promise<ForecastProgress> {
  return parseResponse<ForecastProgress>(await fetch(buildWorkspaceUrl(`/api/forecast/progress/${encodeURIComponent(runId)}`), buildInit()));
}

export async function fetchRuntimeEstimate(request: RuntimeEstimateRequest): Promise<RuntimeEstimateResponse> {
  return parseResponse<RuntimeEstimateResponse>(
    await fetch("/api/runtime/estimate", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    }))
  );
}

export async function fetchRuntimeDetail(runtimeId: string): Promise<RuntimeRunDetail> {
  return parseResponse<RuntimeRunDetail>(await fetch(buildWorkspaceUrl(`/api/runtime/${encodeURIComponent(runtimeId)}`), buildInit()));
}

export async function fetchRuntimeEvents(runtimeId: string): Promise<RuntimeEventsResponse> {
  return parseResponse<RuntimeEventsResponse>(await fetch(buildWorkspaceUrl(`/api/runtime/${encodeURIComponent(runtimeId)}/events`), buildInit()));
}

export function subscribeRuntimeEvents(
  runId: string,
  onEvent: (event: RuntimeEvent) => void,
  afterSequence = 0
): () => void {
  const source = new EventSource(buildWorkspaceUrl(`/api/runtime/${encodeURIComponent(runId)}/events/stream`, { afterSequence }));
  const handleRuntimeEvent = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as RuntimeEvent;
    onEvent(event);
    if (event.eventType === "terminal") source.close();
  };
  source.addEventListener("runtime", handleRuntimeEvent as EventListener);
  return () => source.close();
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
  let closed = false;
  let source: EventSource | null = null;
  let retryTimer = 0;

  const attach = () => {
    if (closed) return;
    source = new EventSource(buildWorkspaceUrl(`/api/forecast/progress/${encodeURIComponent(runId)}/events`));
    source.onmessage = (event) => {
      const progress = JSON.parse(event.data) as ForecastProgress;
      onProgress(progress);
      if (progress.status === "completed" || progress.status === "failed") {
        source?.close();
      }
    };
    source.onerror = () => {
      source?.close();
      source = null;
      if (closed) return;
      retryTimer = window.setTimeout(() => {
        void bootstrap();
      }, 800);
    };
  };

  const bootstrap = async () => {
    while (!closed) {
      try {
        const progress = await fetchForecastProgress(runId);
        onProgress(progress);
        if (progress.status !== "completed" && progress.status !== "failed") {
          attach();
        }
        return;
      } catch {
        await new Promise((resolve) => window.setTimeout(resolve, 400));
      }
    }
  };

  void bootstrap();

  return () => {
    closed = true;
    if (retryTimer) window.clearTimeout(retryTimer);
    source?.close();
  };
}

export async function runFinalForecast(experimentId: string, finalModelId: string, horizon: number, runId?: string): Promise<FinalForecastResponse> {
  return parseResponse<FinalForecastResponse>(
    await fetch("/api/forecast/final", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experimentId, finalModelId, horizon, runId })
    }))
  );
}

export async function fetchExperiments(): Promise<ExperimentListItem[]> {
  return parseResponse<ExperimentListItem[]>(await fetch(buildWorkspaceUrl("/api/experiments"), buildInit()));
}

export async function fetchExperiment(experimentId: string): Promise<ExperimentDetail> {
  return parseResponse<ExperimentDetail>(await fetch(buildWorkspaceUrl(`/api/experiments/${experimentId}`), buildInit()));
}

export async function fetchExperimentFeatureFactory(experimentId: string): Promise<FeatureFactoryResponse> {
  return parseResponse<FeatureFactoryResponse>(await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/feature-factory`), buildInit()));
}

export async function fetchExperimentExplainability(experimentId: string): Promise<ExperimentExplainabilityResponse> {
  return parseResponse<ExperimentExplainabilityResponse>(await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/explainability`), buildInit()));
}

export async function createExperimentAgentRun(experimentId: string, request: AgentRunRequest): Promise<AgentRunResponse> {
  return parseResponse<AgentRunResponse>(
    await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/agent/runs`), buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    }))
  );
}

export async function fetchExperimentAgentRun(experimentId: string, runId: string): Promise<AgentRunDetail> {
  return parseResponse<AgentRunDetail>(
    await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/agent/runs/${encodeURIComponent(runId)}`), buildInit())
  );
}

export async function fetchExperimentAgentRunEvents(experimentId: string, runId: string): Promise<AgentRunEventsResponse> {
  return parseResponse<AgentRunEventsResponse>(
    await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/agent/runs/${encodeURIComponent(runId)}/events`), buildInit())
  );
}

export async function cancelExperimentAgentRun(experimentId: string, runId: string): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/agent/runs/${encodeURIComponent(runId)}/cancel`), buildInit({
      method: "POST"
    }))
  );
}

export async function fetchExperimentAgentHistory(experimentId: string): Promise<AgentHistoryItem[]> {
  return parseResponse<AgentHistoryItem[]>(
    await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/agent/history`), buildInit())
  );
}

export async function fetchExperimentAgentArtifact(experimentId: string, artifactId: string): Promise<AgentArtifact> {
  return parseResponse<AgentArtifact>(
    await fetch(buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/agent/artifacts/${encodeURIComponent(artifactId)}`), buildInit())
  );
}

export async function fetchExperimentManifest(experimentId: string): Promise<ExperimentManifest> {
  return parseResponse<ExperimentManifest>(await fetch(buildWorkspaceUrl(`/api/experiments/${experimentId}/manifest`), buildInit()));
}

export async function prepareExperimentRerun(experimentId: string, uploadId?: string): Promise<ExperimentRerunResponse> {
  return parseResponse<ExperimentRerunResponse>(
    await fetch("/api/experiments/rerun", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experimentId, uploadId })
    }))
  );
}

export async function deleteExperiment(experimentId: string): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(`/api/experiments/${experimentId}`, buildInit({
      method: "DELETE"
    }))
  );
}

export async function testDeepSeekConnection(settings: Pick<DeepSeekSettings, "apiKey" | "baseUrl" | "model">): Promise<DeepSeekConnectionResponse> {
  return parseResponse<DeepSeekConnectionResponse>(
    await fetch("/api/llm/deepseek/test", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
    }, false))
  );
}

export async function analyzeWorkbenchIdea(payload: WorkbenchIdeaAnalyzeRequest): Promise<WorkbenchIdeaAnalyzeResponse> {
  return parseResponse<WorkbenchIdeaAnalyzeResponse>(
    await fetch("/api/workbench-agent/ideas/analyze", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }))
  );
}

export async function generateReport(
  experimentId: string,
  settings: Pick<DeepSeekSettings, "apiKey" | "baseUrl" | "model">,
  reportOptions: ReportOptions
): Promise<ReportResponse> {
  return parseResponse<ReportResponse>(
    await fetch("/api/reports/generate", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experimentId, ...settings, reportOptions })
    }))
  );
}

export async function downloadReportPdf(reportId: string, title: string, visualArtifacts: ReportPdfArtifact[]): Promise<Blob> {
  return parseBlobResponse(
    await fetch(`/api/reports/${encodeURIComponent(reportId)}/pdf`, buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, visualArtifacts })
    }))
  );
}

export async function triggerLocalRebuild(password: string): Promise<LocalRebuildResponse> {
  return parseResponse<LocalRebuildResponse>(
    await fetch("/api/system/local-rebuild", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, delaySeconds: 2 })
    }))
  );
}

export async function createFeedback(request: FeedbackCreateRequest): Promise<FeedbackItem> {
  return parseResponse<FeedbackItem>(
    await fetch("/api/feedback", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    }, false))
  );
}

export async function fetchFeedback(limit = 50): Promise<FeedbackItem[]> {
  const body = await parseResponse<FeedbackListResponse>(await fetch(`/api/feedback?limit=${limit}`, buildInit(undefined, false)));
  return body.items;
}

export async function updateFeedbackStatus(feedbackId: string, status: FeedbackItem["status"]): Promise<FeedbackItem> {
  return parseResponse<FeedbackItem>(
    await fetch(`/api/feedback/${encodeURIComponent(feedbackId)}/status`, buildInit({
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status })
    }, false))
  );
}

export async function testWeComFeedbackNotification(message: string): Promise<FeedbackNotifyTestResponse> {
  return parseResponse<FeedbackNotifyTestResponse>(
    await fetch("/api/feedback/test-wecom", buildInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    }, false))
  );
}

export async function fetchSession(): Promise<AuthSessionResponse> {
  return parseResponse<AuthSessionResponse>(await fetch("/api/auth/me", buildInit(undefined, false)));
}

export async function bootstrapAuth(payload: BootstrapRequest): Promise<AuthSessionResponse> {
  return parseResponse<AuthSessionResponse>(
    await fetch("/api/auth/bootstrap", buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function login(payload: LoginRequest): Promise<AuthSessionResponse> {
  return parseResponse<AuthSessionResponse>(
    await fetch("/api/auth/login", buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function register(payload: RegisterRequest): Promise<AuthSessionResponse> {
  return parseResponse<AuthSessionResponse>(
    await fetch("/api/auth/register", buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function checkUsernameAvailability(username: string): Promise<UsernameAvailabilityResponse> {
  return parseResponse<UsernameAvailabilityResponse>(
    await fetch(`/api/auth/username-availability?username=${encodeURIComponent(username)}`, buildInit(undefined, false))
  );
}

export async function logout(): Promise<void> {
  await parseResponse<{ ok: boolean }>(await fetch("/api/auth/logout", buildInit({ method: "POST" }, false)));
}

export async function fetchUsers(): Promise<UserSummary[]> {
  return parseResponse<UserSummary[]>(await fetch("/api/users", buildInit(undefined, false)));
}

export async function createUser(payload: CreateUserRequest): Promise<UserSummary> {
  return parseResponse<UserSummary>(
    await fetch("/api/users", buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function updateUser(userId: string, payload: UpdateUserRequest): Promise<UserSummary> {
  return parseResponse<UserSummary>(
    await fetch(`/api/users/${encodeURIComponent(userId)}`, buildInit({ method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function updateUserPassword(userId: string, payload: UpdateUserPasswordRequest): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(`/api/users/${encodeURIComponent(userId)}/password`, buildInit({ method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function updateUserGroups(userId: string, payload: UpdateUserGroupsRequest): Promise<UserSummary> {
  return parseResponse<UserSummary>(
    await fetch(`/api/users/${encodeURIComponent(userId)}/groups`, buildInit({ method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function fetchUserGroups(): Promise<UserGroupSummary[]> {
  return parseResponse<UserGroupSummary[]>(await fetch("/api/user-groups", buildInit(undefined, false)));
}

export async function createUserGroup(payload: CreateUserGroupRequest): Promise<UserGroupSummary> {
  return parseResponse<UserGroupSummary>(
    await fetch("/api/user-groups", buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function deleteUserGroup(groupId: string): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(`/api/user-groups/${encodeURIComponent(groupId)}`, buildInit({ method: "DELETE" }, false))
  );
}

export async function fetchWorkspaces(): Promise<WorkspaceSummary[]> {
  return parseResponse<WorkspaceSummary[]>(await fetch("/api/workspaces", buildInit(undefined, false)));
}

export async function createWorkspace(payload: CreateWorkspaceRequest): Promise<WorkspaceSummary> {
  return parseResponse<WorkspaceSummary>(
    await fetch("/api/workspaces", buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, false))
  );
}

export async function updateWorkspace(workspaceId: string, payload: UpdateWorkspaceRequest): Promise<WorkspaceSummary> {
  return parseResponse<WorkspaceSummary>(
    await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`, buildInit({ method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }))
  );
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`, buildInit({ method: "DELETE" }))
  );
}

export async function fetchWorkspaceMembers(workspaceId: string): Promise<WorkspaceMemberResponse[]> {
  return parseResponse<WorkspaceMemberResponse[]>(await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/members`, buildInit()));
}

export async function addWorkspaceMember(workspaceId: string, payload: AddWorkspaceMemberRequest): Promise<WorkspaceMemberResponse> {
  return parseResponse<WorkspaceMemberResponse>(
    await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/members`, buildInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }))
  );
}

export async function removeWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
  await parseResponse<{ ok: boolean }>(
    await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`, buildInit({ method: "DELETE" }))
  );
}

export function manifestDownloadUrl(experimentId: string): string {
  return buildWorkspaceUrl(`/api/experiments/${encodeURIComponent(experimentId)}/manifest/download`);
}
