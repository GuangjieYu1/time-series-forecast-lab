import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { createFeedback, fetchFeedback, testWeComFeedbackNotification, updateFeedbackStatus } from "../../shared/api/client";
import { Badge, PageHeader, SectionCard, controls, surface } from "../../shared/components/Ui";
import type { FeedbackItem, FeedbackKind, FeedbackNotifyStatus, FeedbackStatus } from "../../shared/types/api";

type SubmitState = "idle" | "sending" | "success" | "error";

const kindLabel: Record<FeedbackKind, string> = {
  urgent: "紧急需求",
  feedback: "普通反馈",
  ramble: "碎碎念"
};

const statusLabel: Record<FeedbackStatus, string> = {
  open: "待处理",
  in_progress: "处理中",
  done: "已完成",
  ignored: "已忽略"
};

const notifyLabel: Record<FeedbackNotifyStatus, string> = {
  pending: "等待推送",
  sent: "已推送",
  failed: "推送失败",
  skipped: "未配置通知"
};

function notifyTone(status: FeedbackNotifyStatus): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "sent") return "good";
  if (status === "failed") return "bad";
  if (status === "skipped") return "warn";
  return "neutral";
}

function statusTone(status: FeedbackStatus): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "done") return "good";
  if (status === "in_progress") return "info";
  if (status === "ignored") return "neutral";
  return "warn";
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function FeedbackHistory({ items, onStatusChange }: { items: FeedbackItem[]; onStatusChange: (id: string, status: FeedbackStatus) => void }) {
  if (!items.length) {
    return <div className={`rounded-2xl border border-dashed border-slate-300 p-6 text-sm ${surface.mutedText} dark:border-white/10`}>暂无反馈记录。</div>;
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <article key={item.feedbackId} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-white/10 dark:bg-[#0b1020]/70">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={item.kind === "urgent" ? "bad" : item.kind === "ramble" ? "info" : "neutral"}>{kindLabel[item.kind]}</Badge>
                <Badge tone={notifyTone(item.notifyStatus)}>{notifyLabel[item.notifyStatus]}</Badge>
                <Badge tone={statusTone(item.status)}>{statusLabel[item.status]}</Badge>
              </div>
              <h3 className={`mt-3 text-base font-semibold ${surface.strongText}`}>{item.title || "未填写标题"}</h3>
              <p className={`mt-2 whitespace-pre-wrap break-words text-sm leading-6 ${surface.mutedText}`}>{item.content}</p>
              {item.notifyError ? <p className="mt-2 rounded-xl border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-xs text-amber-300">{item.notifyError}</p> : null}
              <div className={`mt-3 flex flex-wrap gap-3 text-xs ${surface.mutedText}`}>
                <span>ID：{item.feedbackId}</span>
                <span>来源：{item.sourcePage || "未记录"}</span>
                <span>{formatTime(item.createdAt)}</span>
              </div>
            </div>
            <select className={`${controls.input} w-full md:w-40`} value={item.status} onChange={(event) => onStatusChange(item.feedbackId, event.target.value as FeedbackStatus)}>
              <option value="open">待处理</option>
              <option value="in_progress">处理中</option>
              <option value="done">已完成</option>
              <option value="ignored">已忽略</option>
            </select>
          </div>
        </article>
      ))}
    </div>
  );
}

export function FeedbackPage() {
  const location = useLocation();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [testState, setTestState] = useState<SubmitState>("idle");

  const latest = items[0] ?? null;
  const openCount = useMemo(() => items.filter((item) => item.status === "open" || item.status === "in_progress").length, [items]);

  async function refresh() {
    const nextItems = await fetchFeedback(50);
    setItems(nextItems);
  }

  useEffect(() => {
    void refresh().catch((error) => setMessage(error instanceof Error ? error.message : "反馈列表加载失败。"));
  }, []);

  async function submit(kind: FeedbackKind) {
    if (!content.trim()) {
      setSubmitState("error");
      setMessage("请先写下反馈内容。");
      return;
    }
    setSubmitState("sending");
    setMessage(kind === "urgent" ? "紧急需求已进入发送队列，正在推送企业微信。" : "正在保存并推送反馈。");
    try {
      const item = await createFeedback({ kind, title: title.trim() || null, content: content.trim(), sourcePage: location.pathname });
      setItems((current) => [item, ...current.filter((existing) => existing.feedbackId !== item.feedbackId)]);
      setTitle("");
      setContent("");
      setSubmitState("success");
      setMessage(item.notifyStatus === "sent" ? "已保存，并已推送到企业微信。" : `已保存。${item.notifyError ?? notifyLabel[item.notifyStatus]}`);
    } catch (error) {
      setSubmitState("error");
      setMessage(error instanceof Error ? error.message : "反馈提交失败。");
    }
  }

  async function handleStatusChange(feedbackId: string, status: FeedbackStatus) {
    const updated = await updateFeedbackStatus(feedbackId, status);
    setItems((current) => current.map((item) => (item.feedbackId === feedbackId ? updated : item)));
  }

  async function handleTestNotification() {
    setTestState("sending");
    try {
      const result = await testWeComFeedbackNotification("这是一条来自时序预测实验室的反馈通知测试。");
      setTestState(result.success ? "success" : "error");
      setMessage(result.error ? `${result.message} ${result.error}` : result.message);
    } catch (error) {
      setTestState("error");
      setMessage(error instanceof Error ? error.message : "测试通知失败。");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Feedback Console"
        title="反馈与紧急需求"
        description="把紧急需求、产品反馈和碎碎念直接送达维护者；系统会先落库，再通过企业微信机器人推送到手机。"
        action={<button className={controls.secondaryButton} onClick={() => void refresh()}>刷新记录</button>}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <div className={`${surface.softPanel} p-4`}>
          <div className={`text-xs ${surface.mutedText}`}>待跟进</div>
          <div className={`mt-2 text-3xl font-semibold ${surface.strongText}`}>{openCount}</div>
          <p className={`mt-2 text-xs ${surface.mutedText}`}>待处理和处理中反馈总数</p>
        </div>
        <div className={`${surface.softPanel} p-4`}>
          <div className={`text-xs ${surface.mutedText}`}>最近通知</div>
          <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>{latest ? notifyLabel[latest.notifyStatus] : "暂无"}</div>
          <p className={`mt-2 text-xs ${surface.mutedText}`}>{latest ? formatTime(latest.createdAt) : "还没有反馈记录"}</p>
        </div>
        <div className={`${surface.softPanel} p-4`}>
          <div className={`text-xs ${surface.mutedText}`}>通知通道</div>
          <div className={`mt-2 text-xl font-semibold ${surface.strongText}`}>企业微信机器人</div>
          <p className={`mt-2 text-xs ${surface.mutedText}`}>Webhook 仅保存在后端环境变量中</p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_360px]">
        <SectionCard title="写下反馈" description="紧急需求会用红色动作直接推送；碎碎念适合记录灵感、吐槽和小想法。">
          <div className="space-y-4">
            <label className="block">
              <span className={`mb-2 block text-sm font-medium ${surface.strongText}`}>标题</span>
              <input className={controls.input} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：预测运行进度需要更醒目" maxLength={255} />
            </label>
            <label className="block">
              <span className={`mb-2 block text-sm font-medium ${surface.strongText}`}>内容</span>
              <textarea
                className={`${controls.input} min-h-[220px] resize-y leading-6`}
                value={content}
                onChange={(event) => setContent(event.target.value)}
                placeholder="把需求、问题、现场情况或碎碎念写在这里。"
                maxLength={8000}
              />
            </label>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className={`text-xs ${surface.mutedText}`}>{content.length}/8000 · 来源页面：{location.pathname}</div>
              <div className="grid gap-2 sm:flex sm:justify-end">
                <button className={`${controls.dangerButton} w-full sm:w-auto`} disabled={submitState === "sending"} onClick={() => void submit("urgent")}>紧急发送</button>
                <button className={`${controls.secondaryButton} w-full border-cyan-300/30 text-cyan-700 dark:text-cyan-200 sm:w-auto`} disabled={submitState === "sending"} onClick={() => void submit("ramble")}>发送碎碎念</button>
                <button className={`${controls.primaryButton} w-full sm:w-auto`} disabled={submitState === "sending"} onClick={() => void submit("feedback")}>提交反馈</button>
              </div>
            </div>
            {message ? (
              <div className={`rounded-2xl border px-4 py-3 text-sm ${submitState === "error" || testState === "error" ? "border-red-300/40 bg-red-500/10 text-red-200" : "border-emerald-300/30 bg-emerald-400/10 text-emerald-200"}`}>
                {message}
              </div>
            ) : null}
          </div>
        </SectionCard>

        <SectionCard title="手机通知" description="用于验证服务器上的企业微信机器人是否可用。">
          <div className="space-y-4">
            <div className="rounded-2xl border border-white/10 bg-[#0b1020]/70 p-4">
              <div className={`text-sm font-semibold ${surface.strongText}`}>企业微信 Webhook</div>
              <p className={`mt-2 text-sm leading-6 ${surface.mutedText}`}>由后端环境变量 WECOM_FEEDBACK_WEBHOOK_URL 提供，前端不会读取或保存密钥。</p>
            </div>
            <button className={`${controls.secondaryButton} w-full`} disabled={testState === "sending"} onClick={() => void handleTestNotification()}>
              {testState === "sending" ? "正在测试..." : "测试企业微信通知"}
            </button>
            <div className={`text-xs leading-5 ${surface.mutedText}`}>若未配置 webhook，反馈仍会保存，但不会推送到手机。</div>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="反馈记录" description="这里显示最近 50 条记录，方便确认是否已推送和后续处理状态。">
        <FeedbackHistory items={items} onStatusChange={(id, status) => void handleStatusChange(id, status)} />
      </SectionCard>
    </div>
  );
}
