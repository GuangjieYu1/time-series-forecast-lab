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

const loadingMessages = ["正在读取模型排行榜...", "正在分析自动优化轮次...", "正在分析残差分布...", "正在整理最终预测摘要...", "正在生成中文业务建议..."];

type PreviewMode = "rendered" | "source";

function escapeHtml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttribute(value: string) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

function normalizeUrl(value: string) {
  const url = value.trim();
  if (!url || /^javascript:/i.test(url)) return "";
  return url;
}

function renderInlineMarkdown(text: string) {
  let html = escapeHtml(text);
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match, alt: string, url: string) => {
    const safeUrl = normalizeUrl(url);
    if (!safeUrl) return "";
    return `<figure class="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white/80 dark:border-white/10 dark:bg-[#0f172a]"><img class="max-h-[420px] w-full object-contain bg-slate-50 dark:bg-[#020617]" src="${escapeAttribute(safeUrl)}" alt="${escapeAttribute(alt)}" />${alt ? `<figcaption class="border-t border-slate-200 px-4 py-2 text-xs text-slate-500 dark:border-white/10 dark:text-slate-400">${escapeHtml(alt)}</figcaption>` : ""}</figure>`;
  });
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label: string, url: string) => {
    const safeUrl = normalizeUrl(url);
    if (!safeUrl) return escapeHtml(label);
    return `<a class="text-cyan-600 underline underline-offset-4 dark:text-cyan-300" href="${escapeAttribute(safeUrl)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
  });
  html = html.replace(/`([^`]+)`/g, (_match, code: string) => `<code class="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.92em] text-slate-800 dark:bg-[#111827] dark:text-slate-100">${escapeHtml(code)}</code>`);
  html = html.replace(/\*\*([^*]+)\*\*/g, (_match, value: string) => `<strong class="font-semibold text-slate-900 dark:text-white">${escapeHtml(value)}</strong>`);
  return html;
}

function isSpecialBlockStart(line: string, nextLine?: string) {
  const trimmed = line.trim();
  return (
    !trimmed ||
    trimmed.startsWith("```") ||
    /^#{1,3}\s/.test(trimmed) ||
    /^(-{3,}|\*{3,})$/.test(trimmed) ||
    /^>\s?/.test(trimmed) ||
    /^[-*]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed) ||
    (trimmed.includes("|") && !!nextLine && /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(nextLine.trim()))
  );
}

function renderTable(lines: string[]) {
  const rows = lines.map((line) => {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
  });
  const [header, _separator, ...body] = rows;
  const headerHtml = header.map((cell) => `<th class="border-b border-slate-200 px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.08em] text-slate-500 dark:border-white/10 dark:text-slate-400">${renderInlineMarkdown(cell)}</th>`).join("");
  const bodyHtml = body
    .map(
      (row) =>
        `<tr>${row
          .map((cell) => `<td class="border-b border-slate-200 px-3 py-2 align-top text-sm text-slate-700 dark:border-white/10 dark:text-slate-200">${renderInlineMarkdown(cell)}</td>`)
          .join("")}</tr>`
    )
    .join("");
  return `<div class="my-4 overflow-x-auto rounded-2xl border border-slate-200 dark:border-white/10"><table class="min-w-full border-collapse bg-white dark:bg-[#0b1020]"><thead class="bg-slate-50 dark:bg-[#111827]"><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
}

function renderMarkdownToHtml(content: string) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    const nextLine = lines[index + 1];

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim() || "text";
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      html.push(
        `<div class="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-[#0f172a] dark:border-white/10"><div class="border-b border-slate-700/70 px-4 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-300">${escapeHtml(language)}</div><pre class="overflow-x-auto px-4 py-4 text-sm leading-6 text-slate-100"><code>${escapeHtml(codeLines.join("\n"))}</code></pre></div>`
      );
      continue;
    }

    if (/^#{1,3}\s/.test(trimmed)) {
      const level = trimmed.match(/^#+/)?.[0].length ?? 1;
      const text = trimmed.replace(/^#{1,3}\s/, "");
      const className =
        level === 1
          ? "mt-2 text-3xl font-semibold tracking-tight text-slate-950 dark:text-white"
          : level === 2
          ? "mt-6 text-xl font-semibold text-slate-900 dark:text-white"
          : "mt-4 text-base font-semibold text-slate-900 dark:text-white";
      html.push(`<h${level} class="${className}">${renderInlineMarkdown(text)}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      html.push(`<hr class="my-6 border-slate-200 dark:border-white/10" />`);
      index += 1;
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      html.push(
        `<blockquote class="my-4 rounded-r-2xl border-l-4 border-cyan-400 bg-cyan-50/80 px-4 py-3 text-sm leading-7 text-cyan-900 dark:bg-cyan-400/10 dark:text-cyan-100">${quoteLines.map((value) => renderInlineMarkdown(value)).join("<br/>")}</blockquote>`
      );
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      html.push(`<ul class="my-4 list-disc space-y-2 pl-6 text-sm leading-7 text-slate-700 dark:text-slate-200">${items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      html.push(`<ol class="my-4 list-decimal space-y-2 pl-6 text-sm leading-7 text-slate-700 dark:text-slate-200">${items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ol>`);
      continue;
    }

    if (trimmed.includes("|") && nextLine && /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(nextLine.trim())) {
      const tableLines = [line, nextLine];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      html.push(renderTable(tableLines));
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (index < lines.length && !isSpecialBlockStart(lines[index], lines[index + 1])) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    html.push(`<p class="my-3 text-sm leading-7 text-slate-700 dark:text-slate-200">${paragraphLines.map((value) => renderInlineMarkdown(value.trim())).join("<br/>")}</p>`);
  }

  return html.join("\n");
}

function buildHtmlDocument(title: string, content: string) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title><style>
  body{margin:0;background:#f8fafc;color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
  main{max-width:980px;margin:0 auto;padding:32px 20px 48px}
  h1,h2,h3{line-height:1.3}
  p,li,blockquote,td,th{line-height:1.8}
  a{color:#0891b2}
  code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  img{max-width:100%}
  table{width:100%;border-collapse:collapse}
  th,td{border-bottom:1px solid #e2e8f0;padding:8px 12px;text-align:left;vertical-align:top}
  blockquote{margin:16px 0;padding:12px 16px;border-left:4px solid #22d3ee;background:#ecfeff}
  pre{overflow:auto;padding:16px;background:#0f172a;color:#f8fafc;border-radius:16px}
  hr{border:none;border-top:1px solid #cbd5e1;margin:24px 0}
  figure{margin:16px 0}
  figcaption{font-size:12px;color:#475569;margin-top:8px}
  </style></head><body><main>${renderMarkdownToHtml(content)}</main></body></html>`;
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
  const html = useMemo(() => renderMarkdownToHtml(content), [content]);
  return <div className="space-y-3" dangerouslySetInnerHTML={{ __html: html }} />;
}

export function ReportPanel({ experimentId, initialReports = [] }: { experimentId: string; initialReports?: ReportResponse[] }) {
  const [reports, setReports] = useState<ReportResponse[]>(initialReports);
  const [activeReportId, setActiveReportId] = useState(initialReports[0]?.reportId ?? "");
  const [options, setOptions] = useState<ReportOptions>(defaultOptions);
  const [loading, setLoading] = useState(false);
  const [loadingIndex, setLoadingIndex] = useState(0);
  const [previewMode, setPreviewMode] = useState<PreviewMode>("rendered");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const activeReport = useMemo(() => reports.find((report) => report.reportId === activeReportId) ?? reports[0] ?? null, [activeReportId, reports]);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => setLoadingIndex((current) => (current + 1) % loadingMessages.length), 1400);
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
    setMessage("正在分析模型结果、自动优化轮次和最终预测，并生成完整 Markdown 报告...");
    try {
      const report = await generateReport(
        experimentId,
        { apiKey: settings.apiKey.trim(), baseUrl: settings.baseUrl.trim(), model: settings.model.trim() },
        options
      );
      setReports((current) => [report, ...current]);
      setActiveReportId(report.reportId);
      setPreviewMode("rendered");
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
    setMessage("报告 Markdown 已复制到剪贴板。");
  }

  function downloadMarkdown() {
    if (!activeReport) return;
    download(`${activeReport.reportId}.md`, activeReport.contentMarkdown, "text/markdown;charset=utf-8");
  }

  function downloadHtml() {
    if (!activeReport) return;
    const html = buildHtmlDocument(activeReport.reportId, activeReport.contentMarkdown);
    download(`${activeReport.reportId}.html`, html, "text/html;charset=utf-8");
  }

  return (
    <SectionCard
      title="AI 预测总结报告"
      description="报告基于实验摘要、指标、残差、自动优化记录和最终预测生成，不发送原始文件或完整明细。"
      action={<Badge tone={activeReport ? "good" : "neutral"}>{activeReport ? "已有报告" : "未生成"}</Badge>}
      className="overflow-hidden"
    >
      <ErrorBanner message={error} />
      {loading ? <LoadingBlock label={loadingMessages[loadingIndex]} /> : null}
      <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
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
        <div className={`min-h-[420px] ${surface.softPanel} p-0`}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-white/10">
            <div>
              <div className={`text-sm font-semibold ${surface.strongText}`}>报告预览</div>
              <div className={`text-xs ${surface.mutedText}`}>
                {activeReport ? `${activeReport.contentMarkdown.length} 字符 / ${activeReport.contentMarkdown.split("\n").length} 行` : "生成后可在这里查看完整 Markdown 报告"}
              </div>
            </div>
            <div className="flex gap-2">
              <button className={controls.secondaryButton} type="button" disabled={previewMode === "rendered"} onClick={() => setPreviewMode("rendered")}>
                渲染预览
              </button>
              <button className={controls.secondaryButton} type="button" disabled={previewMode === "source"} onClick={() => setPreviewMode("source")}>
                Markdown 源码
              </button>
            </div>
          </div>
          <div className="max-h-[72vh] overflow-auto px-5 py-5">
            {activeReport ? (
              previewMode === "rendered" ? (
                <MarkdownView content={activeReport.contentMarkdown} />
              ) : (
                <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-2xl bg-[#0f172a] p-4 text-sm leading-7 text-slate-100">
                  <code>{activeReport.contentMarkdown}</code>
                </pre>
              )
            ) : (
              <div className="flex h-full min-h-[360px] items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
                还没有报告。配置 DeepSeek 后，可以基于当前实验一键生成中文预测总结，并把自动优化策略与逐轮结果一起写入报告。
              </div>
            )}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
