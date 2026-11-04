"""Credential-free tests of the desktop connection boundary."""

from __future__ import annotations

import json

import pytest

from deployment.client import ClientProfile, forward, load_profile, load_token, main


@pytest.mark.parametrize("url", ["https://mcp.example.org/mcp", "http://127.0.0.1:8765/mcp"])
def test_endpoint_profile_accepts_tls_or_loopback(tmp_path, url):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"url": url, "keychain_service": "test", "keychain_account": "test"}))
    assert load_profile(path).url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.org/mcp",
        "https://user:secret@example.org/mcp",
        "https://example.org/mcp?token=secret",
        "https://example.org/api",
    ],
)
def test_endpoint_profile_refuses_unsafe_or_non_mcp_targets(tmp_path, url):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"url": url, "keychain_service": "test", "keychain_account": "test"}))
    with pytest.raises(ValueError):
        load_profile(path)


def test_keychain_failure_never_exposes_output(monkeypatch, capsys, tmp_path):
    path = tmp_path / "client.json"
    path.write_text(
        json.dumps(
            {"url": "https://mcp.example.org/mcp", "keychain_service": "test", "keychain_account": "test"}
        )
    )

    def fail(*a):
        raise RuntimeError("private-credential-value private-error")

    monkeypatch.setattr("deployment.client.read", fail)
    assert main(["--profile", str(path), "--check"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "private-credential" not in captured.err and "private-error" not in captured.err


def test_keychain_lookup_uses_only_item_references(monkeypatch):
    seen = []

    def read(*args):
        seen.extend(args)
        return "x" * 64

    monkeypatch.setattr("deployment.client.read", read)
    assert (
        load_token(ClientProfile("https://mcp.example.org/mcp", "test-service", "test-account")) == "x" * 64
    )
    assert "x" * 64 not in seen
    assert seen == ["test-service", "test-account"]


async def test_relay_preserves_ids_results_and_cancellation_messages():
    messages = [
        {"id": 7, "result": {"content": []}},
        {"method": "notifications/cancelled", "params": {"requestId": 7}},
    ]

    class Source:
        def __aiter__(self):
            self.iterator = iter(messages)
            return self

        async def __anext__(self):
            try:
                return next(self.iterator)
            except StopIteration:
                raise StopAsyncIteration from None

    class Target:
        def __init__(self):
            self.messages = []

        async def send(self, message):
            self.messages.append(message)

    target = Target()
    await forward(Source(), target)
    assert target.messages == messages
