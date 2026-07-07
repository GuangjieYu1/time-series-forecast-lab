from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.db.models import FeedbackRecord


@dataclass(frozen=True)
class WeComNotifyResult:
    status: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "sent"


def _feedback_kind_label(kind: str) -> str:
    return {
        "urgent": "紧急需求",
        "feedback": "普通反馈",
        "ramble": "碎碎念",
    }.get(kind, "反馈")


def _post_wecom_message(webhook_url: str, payload: dict[str, Any], timeout_seconds: float) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8", errors="replace")
        if response.status >= 400:
            raise RuntimeError(f"企业微信机器人返回 HTTP {response.status}: {raw[:300]}")
        try:
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            result = {}
        if isinstance(result, dict) and result.get("errcode") not in (None, 0):
            message = result.get("errmsg") or "企业微信机器人返回失败。"
            raise RuntimeError(str(message))


def build_feedback_markdown(record: FeedbackRecord) -> str:
    label = _feedback_kind_label(record.kind)
    title = record.title or "未填写标题"
    created_at = record.created_at.astimezone(timezone.utc).isoformat()
    content = record.content.strip()
    source_page = record.source_page or "未记录"
    return "\n".join(
        [
            f"# [{label}] {title}",
            "",
            content,
            "",
            f"> 反馈 ID：{record.id}",
            f"> 来源页面：{source_page}",
            f"> 创建时间：{created_at}",
        ]
    )


def notify_feedback(record: FeedbackRecord, settings: Settings) -> WeComNotifyResult:
    webhook_url = settings.wecom_feedback_webhook_url
    if not webhook_url:
        return WeComNotifyResult(status="skipped", error="未配置企业微信机器人 webhook，反馈已保存但不会推送到手机。")

    payload = {"msgtype": "markdown", "markdown": {"content": build_feedback_markdown(record)}}
    try:
        _post_wecom_message(webhook_url, payload, settings.feedback_notification_timeout_seconds)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        return WeComNotifyResult(status="failed", error=f"企业微信通知发送失败：{exc}")
    return WeComNotifyResult(status="sent")


def notify_test_message(message: str, settings: Settings) -> WeComNotifyResult:
    webhook_url = settings.wecom_feedback_webhook_url
    if not webhook_url:
        return WeComNotifyResult(status="skipped", error="未配置企业微信机器人 webhook。")
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": f"# [通知测试]\n\n{message}\n\n> 发送时间：{now}"},
    }
    try:
        _post_wecom_message(webhook_url, payload, settings.feedback_notification_timeout_seconds)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        return WeComNotifyResult(status="failed", error=f"企业微信通知发送失败：{exc}")
    return WeComNotifyResult(status="sent")
