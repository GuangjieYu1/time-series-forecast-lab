import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { generateReport } from "../../shared/api/client";
import { loadDeepSeekSettings } from "../../shared/api/deepseekSettings";
import { ErrorBanner, LoadingBlock } from "../../shared/components/Status";
import { Badge, controls, SectionCard, surface } from "../../shared/components/Ui";
import type { ReportOptions, ReportResponse } from "../../shared/types/api";

const defaultOptions: ReportOptions = {
  language: "zh-CN",
  style: "business",
  length: "medium",
  includeModelComparison: true,
  includeResidualAnalysis: true,
  includeFinalForecast: true,
  includeWarnings: true
};

const loadingMessages = ["正在读取模型排行榜...", "正在分析残差分布...", "正在整理最终预测摘要...", "正在生成中文业务建议..."];

function escapeHtml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function download(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function MarkdownView({ content }: { content: string }) {
  const blocks = content.split(/\n+/);
  return (
    <div className="space-y-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
      {blocks.map((block, index) => {
        if (block.startsWith("# ")) return <h1 key={index} className="text-2xl font-semibold text-slate-950 dark:text-white">{block.slice(2)}</h1>;
        if (block.startsWith("## ")) return <h2 key={index} className="pt-3 text-lg font-semibold text-slate-900 dark:text-white">{block.slice(3)}</h2>;
        if (block.startsWith("### ")) return <h3 key={index} className="pt-2 text-base font-semibold text-slate-900 dark:text-white">{block.slice(4)}</h3>;
        if (block.startsWith("- ")) return <p key={index} className="pl-4">• {block.slice(2)}</p>;
        if (/^\d+\.\s/.test(block)) return <p key={index} className="pl-4">{block}</p>;
        return <p key={index}>{block}</p>;
      })}
    </div>
  );
}

export function ReportPanel({ experimentId, initialReports = [] }: { experimentId: string; initialReports?: ReportResponse[] }) {
  const [reports, setReports] = useState<ReportResponse[]>(initialReports);
  const [activeReportId, setActiveReportId] = useState(initialReports[0]?.reportId ?? "");
  const [options, setOptions] = useState<ReportOptions>(defaultOptions);
  const [loading, setLoading] = useState(false);
  const [loadingIndex, setLoadingIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const activeReport = useMemo(() => reports.find((report) => report.reportId === activeReportId) ?? reports[0] ?? null, [activeReportId, reports]);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => setLoadingIndex((index) => (index + 1) % loadingMessages.length), 1400);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function submit() {
    const settings = loadDeepSeekSettings();
    if (!settings.apiKey.trim()) {
      setError("请先在 API 设置页配置 DeepSeek API Key。");
      return;
    }
    setLoading(true);
    setError(null);
    setMessage("正在分析模型结果并生成中文报告...");
    try {
      const report = await generateReport(
        experimentId,
        { apiKey: settings.apiKey.trim(), baseUrl: settings.baseUrl.trim(), model: settings.model.trim() },
        options
      );
      setReports((current) => [report, ...current]);
      setActiveReportId(report.reportId);
      setMessage("报告已生成并保存到实验详情。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "报告生成失败，请检查 DeepSeek API Key、余额或网络连接。");
    } finally {
      setLoading(false);
    }
  }

  async function copyReport() {
    if (!activeReport) return;
    await navigator.clipboard.writeText(activeReport.contentMarkdown);
    setMessage("报告已复制到剪贴板。");
  }

  function downloadMarkdown() {
    if (!activeReport) return;
    download(`${activeReport.reportId}.md`, activeReport.contentMarkdown, "text/markdown;charset=utf-8");
  }

  function downloadHtml() {
    if (!activeReport) return;
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${activeReport.reportId}</title></head><body><pre>${escapeHtml(activeReport.contentMarkdown)}</pre></body></html>`;
    download(`${activeReport.reportId}.html`, html, "text/html;charset=utf-8");
  }

  return (
    <SectionCard
      title="AI 预测总结报告"
      description="报告基于实验摘要、指标、残差和最终预测生成，不发送原始文件或完整明细。"
      action={<Badge tone={activeReport ? "good" : "neutral"}>{activeReport ? "已有报告" : "未生成"}</Badge>}
      className="overflow-hidden"
    >
      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label={loadingMessages[loadingIndex]} /> : null}
      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-4">
          <div className="rounded-3xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-cyan-50 p-4 dark:border-indigo-300/20 dark:from-indigo-400/10 dark:to-cyan-400/10">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-600 dark:text-indigo-300">AI Report</div>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              未配置 DeepSeek API 时不会发送任何请求。配置后，报告只使用实验摘要和图表数据，不包含上传原文件。
            </p>
          </div>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">报告风格</span>
            <select className={controls.input} value={options.style} onChange={(event) => setOptions((current) => ({ ...current, style: event.target.value as ReportOptions["style"] }))}>
              <option value="business">业务解读</option>
              <option value="technical">技术分析</option>
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">报告长度</span>
            <select className={controls.input} value={options.length} onChange={(event) => setOptions((current) => ({ ...current, length: event.target.value as ReportOptions["length"] }))}>
              <option value="short">简短</option>
              <option value="medium">标准</option>
              <option value="long">详细</option>
            </select>
          </label>
          {reports.length ? (
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">历史报告</span>
              <select className={controls.input} value={activeReport?.reportId ?? ""} onChange={(event) => setActiveReportId(event.target.value)}>
                {reports.map((report) => (
                  <option key={report.reportId} value={report.reportId}>
                    {new Date(report.createdAt).toLocaleString()} / {report.model}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <button className={controls.primaryButton} type="button" disabled={loading} onClick={() => void submit()}>
              一键生成总结报告
            </button>
            <Link className={controls.secondaryButton} to="/settings">
              配置 API Key
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <button className={controls.secondaryButton} type="button" disabled={!activeReport} onClick={() => void copyReport()}>
              复制
            </button>
            <button className={controls.secondaryButton} type="button" disabled={!activeReport} onClick={downloadMarkdown}>
              下载 Markdown
            </button>
            <button className={controls.secondaryButton} type="button" disabled={!activeReport} onClick={downloadHtml}>
              下载 HTML
            </button>
          </div>
          {message ? <p className="rounded-2xl bg-slate-100 p-3 text-sm text-slate-600 dark:bg-[#151b2e] dark:text-slate-300">{message}</p> : null}
        </div>
        <div className={`min-h-[420px] ${surface.softPanel} p-5`}>
          {activeReport ? (
            <MarkdownView content={activeReport.contentMarkdown} />
          ) : (
            <div className="flex h-full items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
              还没有报告。配置 DeepSeek 后，可以基于当前实验一键生成中文预测总结。
            </div>
          )}
        </div>
      </div>
    </SectionCard>
  );
}
