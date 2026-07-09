import { create } from "zustand";
import { clearSelectedWorkspaceId, loadSelectedWorkspaceId, saveSelectedWorkspaceId, setCurrentAuthUserId } from "../shared/api/workspaceSession";
import type { AuthSessionResponse, AuthUser, ExperimentRerunResponse, FinalForecastResponse, ForecastRunResponse, SheetPreview, UploadPreviewResponse, WorkspaceSummary } from "../shared/types/api";

interface LabState {
  currentUser: AuthUser | null;
  workspaces: WorkspaceSummary[];
  selectedWorkspaceId: string | null;
  upload: UploadPreviewResponse | null;
  selectedSheet: SheetPreview | null;
  forecastResult: ForecastRunResponse | null;
  finalForecast: FinalForecastResponse | null;
  rerunDraft: ExperimentRerunResponse | null;
  setSession: (session: AuthSessionResponse) => void;
  clearSession: () => void;
  selectWorkspace: (workspaceId: string) => void;
  setUpload: (upload: UploadPreviewResponse) => void;
  setSelectedSheet: (sheet: SheetPreview) => void;
  setForecastResult: (result: ForecastRunResponse) => void;
  setFinalForecast: (result: FinalForecastResponse) => void;
  beginRerunDraft: (draft: ExperimentRerunResponse) => void;
  setRerunDraft: (draft: ExperimentRerunResponse | null) => void;
}

export const useLabStore = create<LabState>((set) => ({
  currentUser: null,
  workspaces: [],
  selectedWorkspaceId: null,
  upload: null,
  selectedSheet: null,
  forecastResult: null,
  finalForecast: null,
  rerunDraft: null,
  setSession: (session) =>
    set((state) => {
      const nextUser = session.user ?? null;
      const availableWorkspaces = session.workspaces ?? [];
      setCurrentAuthUserId(nextUser?.userId ?? null);
      const remembered = nextUser ? (loadSelectedWorkspaceId(nextUser.userId) ?? state.selectedWorkspaceId) : null;
      const rememberedWorkspaceId = nextUser ? (availableWorkspaces.find((item) => item.workspaceId === remembered)?.workspaceId ?? null) : null;
      const resolvedWorkspaceId = rememberedWorkspaceId ?? session.defaultWorkspaceId ?? availableWorkspaces[0]?.workspaceId ?? null;
      if (nextUser && resolvedWorkspaceId) {
        saveSelectedWorkspaceId(nextUser.userId, resolvedWorkspaceId);
      }
      return {
        currentUser: nextUser,
        workspaces: availableWorkspaces,
        selectedWorkspaceId: resolvedWorkspaceId,
      };
    }),
  clearSession: () => {
    const currentUserId = useLabStore.getState().currentUser?.userId ?? null;
    clearSelectedWorkspaceId(currentUserId);
    setCurrentAuthUserId(null);
    set({
      currentUser: null,
      workspaces: [],
      selectedWorkspaceId: null,
      upload: null,
      selectedSheet: null,
      forecastResult: null,
      finalForecast: null,
      rerunDraft: null,
    });
  },
  selectWorkspace: (workspaceId) =>
    set((state) => {
      if (state.currentUser) {
        saveSelectedWorkspaceId(state.currentUser.userId, workspaceId);
      }
      return {
        selectedWorkspaceId: workspaceId,
        upload: null,
        selectedSheet: null,
        forecastResult: null,
        finalForecast: null,
        rerunDraft: null,
      };
    }),
  setUpload: (upload) => set({ upload, selectedSheet: upload.sheets[0] ?? null, forecastResult: null, finalForecast: null }),
  setSelectedSheet: (selectedSheet) => set({ selectedSheet }),
  setForecastResult: (forecastResult) => set({ forecastResult, finalForecast: null }),
  setFinalForecast: (finalForecast) => set({ finalForecast }),
  beginRerunDraft: (rerunDraft) =>
    set({
      rerunDraft,
      upload: null,
      selectedSheet: null,
      forecastResult: null,
      finalForecast: null
    }),
  setRerunDraft: (rerunDraft) =>
    set({
      rerunDraft
    })
}));
