import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { useLabStore } from "../../app/store";
import { fetchSheetPreview, uploadPreview } from "../../shared/api/client";
import { EmptyState, ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { DataTable } from "../../shared/components/Table";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import type { ColumnProfile, SheetPreview } from "../../shared/types/api";

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function typeLabel(column: ColumnProfile) {
  if (column.inferredType === "datetime") return "时间列";
  if (column.inferredType === "number") return "数值列";
  if (/id|no|code|编号|单号/i.test(column.name)) return "疑似 ID";
  if (column.inferredType === "boolean") return "布尔列";
  if (column.inferredType === "empty") return "空列";
  return "文本列";
}

function typeTone(column: ColumnProfile): "neutral" | "good" | "warn" | "bad" | "info" {
  if (column.inferredType === "datetime") return "info";
  if (column.inferredType === "number") return "good";
  if (column.inferredType === "empty" || column.nullCountInPreview > column.nonNullCountInPreview) return "bad";
  if (/id|no|code|编号|单号/i.test(column.name)) return "warn";
  return "neutral";
}

function PreviewTable({ sheet }: { sheet: SheetPreview }) {
  const columns = useMemo<ColumnDef<Record<string, unknown>>[]>(
    () =>
      sheet.columns.map((column) => ({
        accessorKey: column.name,
        header: column.name,
        cell: (info) => formatValue(info.getValue())
      })),
    [sheet]
  );
  return <DataTable data={sheet.previewRows} columns={columns} />;
}

function ColumnProfilePanel({ columns }: { columns: ColumnProfile[] }) {
  return (
    <div className="space-y-3">
      {columns.map((column) => (
        <div key={column.name} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#151b2e]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate font-medium text-slate-900 dark:text-white">{column.name}</div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                非空 {column.nonNullCountInPreview} / 空值 {column.nullCountInPreview}
              </div>
            </div>
            <Badge tone={typeTone(column)}>{typeLabel(column)}</Badge>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {column.sampleValues.slice(0, 3).map((value, index) => (
              <span key={index} className="max-w-full truncate rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-[#0b1020] dark:text-slate-300">
                {formatValue(value)}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function UploadPage() {
  const navigate = useNavigate();
  const { upload, selectedSheet, setUpload, setSelectedSheet } = useLabStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File | null) {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const response = await uploadPreview(file);
      setUpload(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文件上传失败，请检查格式或文件大小。");
    } finally {
      setLoading(false);
    }
  }

  async function selectSheet(sheetName: string) {
    if (!upload) return;
    setLoading(true);
    setError(null);
    try {
      const sheet = await fetchSheetPreview(upload.uploadId, sheetName);
      setSelectedSheet(sheet);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sheet 预览加载失败。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="数据导入"
        title="上传工作台"
        description="后端负责解析 CSV / XLS / XLSX、识别 Sheet、推断字段类型；前端只接收前 100 行预览，适合大文件验收。"
      />

      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label="正在由后端解析文件预览..." /> : null}

      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        <section className={`${surface.workbench} p-6`}>
          <div className="rounded-[28px] border border-dashed border-indigo-300 bg-gradient-to-br from-indigo-50 to-cyan-50 p-8 text-center dark:border-indigo-300/30 dark:from-indigo-400/10 dark:to-cyan-400/10">
            <div className="mx-auto max-w-2xl">
              <Badge tone="info">支持 CSV / XLSX / XLS</Badge>
              <h2 className="mt-5 text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">拖拽或选择时间序列表格</h2>
              <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-slate-300">
                适合上传航班明细、客流、销量、能耗、M4 / ETT 等时间序列数据。原始文件只在临时目录中保留，实验完成后删除。
              </p>
              <label className={`${controls.primaryButton} mt-6 cursor-pointer`}>
                上传文件
                <input className="hidden" type="file" accept=".csv,.xlsx,.xls" onChange={(event) => void handleFile(event.target.files?.[0] ?? null)} />
              </label>
            </div>
          </div>

          {upload && selectedSheet ? (
            <div className="mt-6 space-y-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-950 dark:text-white">{upload.fileName}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{Math.round(upload.fileSize / 1024)} KB / {upload.sheets.length} 个 Sheet</div>
                </div>
                <button className={controls.primaryButton} onClick={() => navigate("/forecast")}>
                  进入预测实验
                </button>
              </div>

              <div className="flex flex-wrap gap-2">
                {upload.sheets.map((sheet) => (
                  <button
                    key={sheet.sheetName}
                    className={`rounded-xl border px-3 py-2 text-sm font-semibold transition ${
                      selectedSheet.sheetName === sheet.sheetName
                        ? "border-indigo-500 bg-indigo-50 text-indigo-700 dark:border-indigo-300/40 dark:bg-indigo-400/10 dark:text-indigo-200"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
                    }`}
                    onClick={() => void selectSheet(sheet.sheetName)}
                  >
                    {sheet.sheetName}
                    <span className="ml-2 text-xs text-slate-400">{sheet.rowCountApprox ?? "?"} 行</span>
                  </button>
                ))}
              </div>

              <SectionCard title="前 100 行预览" description="用于确认字段和样例值，前端不会完整解析大文件。">
                <PreviewTable sheet={selectedSheet} />
              </SectionCard>
            </div>
          ) : (
            <div className="mt-6">
              <EmptyState title="尚未上传文件" detail="上传后会显示 Sheet 标签页、字段识别和前 100 行数据预览。" />
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <StatCard label="解析策略" value="后端流式" hint="CSV 流式读取，Excel 按 Sheet 预览" tone="info" />
          <StatCard label="预览上限" value="100 行" hint="控制浏览器内存和渲染压力" tone="good" />
          <StatCard label="存储策略" value="不落库" hint="原始文件不会写入实验历史" tone="warn" />
          <SectionCard title="字段识别面板" description={selectedSheet ? "字段类型、样例值和缺失情况。" : "上传后展示字段画像。"}>
            {selectedSheet ? <ColumnProfilePanel columns={selectedSheet.columns} /> : <EmptyState title="等待文件解析" />}
          </SectionCard>
        </aside>
      </div>
    </div>
  );
}
