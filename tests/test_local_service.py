"""The local runtime ignores ambient privileges and refuses unsafe profiles."""

import json

import pytest

from deployment.service import load_service
from pretix_agent_mcp.config import ConfigError


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr("deployment.service.read", lambda *args: "x" * 64)
    data = {
        "keychain": {"service": "test", "api_account": "api", "client_account": "client"},
        "PRETIX_BASE_URL": "https://pretix.eu",
        "PRETIX_ORGANIZER": "kalnoky",
        "PRETIX_EVENT_ALLOWLIST": ["test-event"],
        "MCP_CAPABILITIES": ["read", "write", "write:high-risk"],
        "MCP_AUTO_APPROVE": [],
        "PII_MODE": "redacted",
        "MCP_HOST": "127.0.0.1",
    }
    path = tmp_path / "config.json"
    return data, path


def test_runtime_does_not_inherit_agent_permission_environment(profile, monkeypatch):
    data, path = profile
    path.write_text(json.dumps(data))
    monkeypatch.setenv("MCP_AUTO_APPROVE", "delete_product,cancel_order")
    monkeypatch.setenv("PRETIX_EVENT_ALLOWLIST", "")
    monkeypatch.setenv("PII_MODE", "full")
    config = load_service(path)
    assert config.auto_approve == []
    assert config.event_allowlist == ["test-event"]
    assert config.pii_mode == "redacted"


@pytest.mark.parametrize(
    "change",
    [
        {"PRETIX_API_TOKEN": "do-not-store-in-files"},
        {"MCP_BEARER_TOKEN": "do-not-store-in-files"},
        {"MCP_HOST": "0.0.0.0"},
        {"PRETIX_EVENT_ALLOWLIST": []},
        {"MCP_AUTO_APPROVE": ["cancel_order"]},
        {"PII_MODE": "full"},
        {"PRETIX_BASE_URL": "https://untrusted.example"},
    ],
)
def test_runtime_refuses_unapproved_deployment_expansion(profile, change):
    data, path = profile
    data.update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(ConfigError):
        load_service(path)
