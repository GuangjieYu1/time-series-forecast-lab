import { create } from "zustand";
import type { ExperimentRerunResponse, FinalForecastResponse, ForecastRunResponse, SheetPreview, UploadPreviewResponse } from "../shared/types/api";

interface LabState {
  upload: UploadPreviewResponse | null;
  selectedSheet: SheetPreview | null;
  forecastResult: ForecastRunResponse | null;
  finalForecast: FinalForecastResponse | null;
  rerunDraft: ExperimentRerunResponse | null;
  setUpload: (upload: UploadPreviewResponse) => void;
  setSelectedSheet: (sheet: SheetPreview) => void;
  setForecastResult: (result: ForecastRunResponse) => void;
  setFinalForecast: (result: FinalForecastResponse) => void;
  beginRerunDraft: (draft: ExperimentRerunResponse) => void;
  setRerunDraft: (draft: ExperimentRerunResponse | null) => void;
}

export const useLabStore = create<LabState>((set) => ({
  upload: null,
  selectedSheet: null,
  forecastResult: null,
  finalForecast: null,
  rerunDraft: null,
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
