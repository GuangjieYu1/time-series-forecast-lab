from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.models import FeedbackRecord
from app.db.session import SessionLocal
from app.main import app
from app.services.wecom_notifier import WeComNotifyResult


def _cleanup(feedback_id: str) -> None:
    db = SessionLocal()
    try:
        record = db.get(FeedbackRecord, feedback_id)
        if record is not None:
            db.delete(record)
            db.commit()
    finally:
        db.close()


def test_feedback_without_wecom_webhook_is_saved_and_skipped(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wecom_feedback_webhook_url", None)

    response = TestClient(app).post(
        "/api/feedback",
        json={"kind": "ramble", "title": "测试碎碎念", "content": "这是一条测试反馈。", "sourcePage": "/feedback"},
    )

    assert response.status_code == 200
    body = response.json()
    try:
        assert body["kind"] == "ramble"
        assert body["status"] == "open"
        assert body["notifyStatus"] == "skipped"
        assert "webhook" in body["notifyError"]
    finally:
        _cleanup(body["feedbackId"])


def test_urgent_feedback_marks_notification_sent(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wecom_feedback_webhook_url", "https://example.invalid/wecom")

    def fake_notify(record, settings):
        assert record.kind == "urgent"
        return WeComNotifyResult(status="sent")

    monkeypatch.setattr("app.api.feedback.notify_feedback", fake_notify)

    response = TestClient(app).post(
        "/api/feedback",
        json={"kind": "urgent", "title": "紧急测试", "content": "需要马上看到。", "sourcePage": "/forecast"},
    )

    assert response.status_code == 200
    body = response.json()
    try:
        assert body["kind"] == "urgent"
        assert body["notifyStatus"] == "sent"
        assert body["notifyError"] is None
    finally:
        _cleanup(body["feedbackId"])


def test_feedback_notification_failure_keeps_record(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wecom_feedback_webhook_url", "https://example.invalid/wecom")

    def fake_notify(record, settings):
        return WeComNotifyResult(status="failed", error="企业微信通知发送失败：timeout")

    monkeypatch.setattr("app.api.feedback.notify_feedback", fake_notify)

    response = TestClient(app).post(
        "/api/feedback",
        json={"kind": "feedback", "title": "失败隔离", "content": "通知失败也要保存。", "sourcePage": "/models"},
    )

    assert response.status_code == 200
    body = response.json()
    try:
        assert body["notifyStatus"] == "failed"
        assert "timeout" in body["notifyError"]
        listed = TestClient(app).get("/api/feedback?limit=10").json()["items"]
        assert any(item["feedbackId"] == body["feedbackId"] for item in listed)
    finally:
        _cleanup(body["feedbackId"])


def test_feedback_status_can_be_updated(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wecom_feedback_webhook_url", None)
    client = TestClient(app)
    created = client.post(
        "/api/feedback",
        json={"kind": "feedback", "title": "状态测试", "content": "更新状态。", "sourcePage": "/feedback"},
    ).json()
    try:
        response = client.patch(f"/api/feedback/{created['feedbackId']}/status", json={"status": "done"})
        assert response.status_code == 200
        assert response.json()["status"] == "done"
    finally:
        _cleanup(created["feedbackId"])
