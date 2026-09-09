from __future__ import annotations

import httpx
import pytest

from app.services import deepseek


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    response_payload: dict = {}
    last_payload: dict | None = None

    def __init__(self, *, timeout: int):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def post(self, url: str, *, headers: dict[str, str], json: dict) -> _FakeResponse:
        del url, headers
        type(self).last_payload = json
        return _FakeResponse(type(self).response_payload)


def test_report_completion_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.response_payload = {
        "choices": [{"message": {"content": "报告正文"}, "finish_reason": "stop"}]
    }
    monkeypatch.setattr(deepseek.httpx, "Client", _FakeClient)

    content, finish_reason = deepseek._request_completion(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "生成报告"}],
        max_tokens=1800,
    )

    assert content == "报告正文"
    assert finish_reason == "stop"
    assert _FakeClient.last_payload is not None
    assert _FakeClient.last_payload["thinking"] == {"type": "disabled"}


def test_empty_reasoning_response_remains_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.response_payload = {
        "choices": [
            {
                "message": {"content": "", "reasoning_content": "正在思考"},
                "finish_reason": "length",
            }
        ]
    }
    monkeypatch.setattr(deepseek.httpx, "Client", _FakeClient)

    with pytest.raises(deepseek.AppError) as error:
        deepseek._request_completion(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "生成报告"}],
            max_tokens=1800,
        )
    assert error.value.code == "DEEPSEEK_EMPTY_REPORT"
    assert error.value.details["finishReason"] == "length"


def test_connection_check_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.response_payload = {
        "choices": [{"message": {"content": "连接成功"}, "finish_reason": "stop"}]
    }
    monkeypatch.setattr(deepseek.httpx, "Client", _FakeClient)

    response = deepseek.test_deepseek_connection(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
    )

    assert response.success is True
    assert _FakeClient.last_payload is not None
    assert _FakeClient.last_payload["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (400, "请求参数"),
        (401, "API Key 无效"),
        (402, "余额不足"),
        (429, "请求过于频繁"),
        (503, "暂时不可用"),
    ],
)
def test_http_error_messages_are_actionable(status_code: int, message: str) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status_code, request=request)
    error = httpx.HTTPStatusError("request failed", request=request, response=response)

    assert message in deepseek._sanitize_error(error)
