from __future__ import annotations

from app.services import deepseek as deepseek_module


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ]
        }


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, str, dict, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, *, headers: dict, json: dict):
        self.calls.append((url, headers.get("Authorization", ""), json, headers))
        return _FakeResponse()


def test_request_deepseek_text_accepts_legacy_prompt_signature(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(deepseek_module.httpx, "Client", lambda *args, **kwargs: fake_client)

    content = deepseek_module.request_deepseek_text(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        system_prompt="system message",
        user_prompt="user message",
        max_tokens=128,
        temperature=0.1,
    )

    assert content == "ok"
    assert len(fake_client.calls) == 1
    payload = fake_client.calls[0][2]
    assert payload["messages"] == [
        {"role": "system", "content": "system message"},
        {"role": "user", "content": "user message"},
    ]


def test_request_deepseek_text_accepts_block_content(monkeypatch):
    class _BlockResponse(_FakeResponse):
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "第一段"},
                                {"type": "text", "text": "第二段"},
                            ]
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    fake_client = _FakeClient()
    monkeypatch.setattr(fake_client, "post", lambda url, *, headers, json: _BlockResponse())
    monkeypatch.setattr(deepseek_module.httpx, "Client", lambda *args, **kwargs: fake_client)

    content = deepseek_module.request_deepseek_text(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=128,
    )

    assert content == "第一段\n第二段"


def test_request_deepseek_text_falls_back_to_reasoning_content(monkeypatch):
    class _ReasoningResponse(_FakeResponse):
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "这是 reasoning fallback",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    fake_client = _FakeClient()
    monkeypatch.setattr(fake_client, "post", lambda url, *, headers, json: _ReasoningResponse())
    monkeypatch.setattr(deepseek_module.httpx, "Client", lambda *args, **kwargs: fake_client)

    content = deepseek_module.request_deepseek_text(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=128,
    )

    assert content == "这是 reasoning fallback"
