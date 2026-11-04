"""Regressions for the reviewed fork's write-access boundaries."""

from __future__ import annotations

import json
import stat

import pytest

from pretix_agent_mcp.cli import main
from pretix_agent_mcp.config import ConfigError
from pretix_agent_mcp.pending import ApprovalError
from pretix_agent_mcp.redact import redact
from pretix_agent_mcp.registry import REGISTRY, execute_approved, run_tool
from pretix_agent_mcp.validate import ValidationError


async def invoke(app, name, /, **kwargs):
    return await run_tool(app, REGISTRY[name], kwargs)


@pytest.mark.parametrize("elapsed", [10, 11, 1000])
async def test_approved_action_expires_before_execution(make_app, api, monkeypatch, elapsed):
    clock = [1000.0]
    monkeypatch.setattr("pretix_agent_mcp.pending.time.time", lambda: clock[0])
    app = make_app(APPROVAL_TTL_SECONDS="10")
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": True})
    api.page("GET", "events/conf27/orders", [])
    action = await invoke(app, "delete_event", event="conf27")
    action_id = action["pending_action_id"]
    app.pending.decide(action_id, "approved")
    clock[0] += elapsed
    with pytest.raises(ApprovalError, match="expired"):
        await execute_approved(app, action_id)
    assert app.pending.get(action_id).state == "expired"
    assert api.sent("DELETE", "events/conf27") == []


def test_allowlist_cannot_enable_writes_under_read_only_capability(make_config):
    cfg = make_config(MCP_CAPABILITIES="read", MCP_TOOL_ALLOWLIST="create_event,list_events")
    assert not cfg.tool_enabled("create_event", "write")
    assert cfg.tool_enabled("list_events", "read")


def test_test_only_profile_requires_explicit_events(make_config):
    with pytest.raises(ConfigError, match="explicit PRETIX_EVENT_ALLOWLIST"):
        make_config(PRETIX_TEST_MODE_ONLY="true")
    with pytest.raises(ConfigError, match="true.*false"):
        make_config(PRETIX_TEST_MODE_ONLY="maybe")


async def test_test_only_writes_are_useful_but_cannot_publish(make_app, api):
    app = make_app(PRETIX_TEST_MODE_ONLY="true", PRETIX_EVENT_ALLOWLIST="conf27")
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": True})
    api.route("POST", "events/conf27/items", {"id": 3, "name": "Test ticket"})
    result = await invoke(app, "create_product", event="conf27", name="Test ticket", default_price="25.00")
    assert result["created"]["id"] == 3
    assert api.sent("POST", "events/conf27/items")[0]["default_price"] == "25.00"
    with pytest.raises(PermissionError, match="publishing is disabled"):
        await invoke(app, "publish_event", event="conf27")
    assert api.sent("PATCH", "events/conf27") == []


@pytest.mark.parametrize("testmode", [False, None, "true"])
async def test_test_only_profile_fails_closed_on_production_or_unknown_mode(make_app, api, testmode):
    app = make_app(PRETIX_TEST_MODE_ONLY="true", PRETIX_EVENT_ALLOWLIST="conf27")
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": testmode})
    with pytest.raises(PermissionError, match="test-mode event"):
        await invoke(app, "create_voucher", event="conf27", value="0.00")
    assert api.sent("POST", "events/conf27/vouchers") == []


async def test_test_only_profile_blocks_foreign_events_before_network(make_app, api):
    app = make_app(PRETIX_TEST_MODE_ONLY="true", PRETIX_EVENT_ALLOWLIST="conf27")
    with pytest.raises(ValidationError, match="allowlist"):
        await invoke(app, "create_product", event="other", name="Wrong event")
    assert api.requests == []


async def test_test_only_profile_can_create_an_allowed_test_event(make_app, api):
    app = make_app(PRETIX_TEST_MODE_ONLY="true", PRETIX_EVENT_ALLOWLIST="conf27")
    api.route("POST", "events", {"slug": "conf27", "live": False, "testmode": True})
    await invoke(app, "create_event", event="conf27", name="TEST", date_from="2027-01-01T10:00:00Z")
    payload = api.sent("POST", "events")[0]
    assert payload["testmode"] is True and payload["live"] is False


async def test_approved_action_obeys_new_test_only_profile(make_app, api):
    app = make_app()
    api.route("GET", "events/conf27", {"slug": "conf27", "live": True, "testmode": False})
    api.page("GET", "events/conf27/orders", [])
    action_id = (await invoke(app, "delete_event", event="conf27"))["pending_action_id"]
    app.pending.decide(action_id, "approved")
    locked = make_app(PRETIX_TEST_MODE_ONLY="true", PRETIX_EVENT_ALLOWLIST="conf27")
    with pytest.raises(PermissionError, match="test-mode event"):
        await execute_approved(locked, action_id)
    assert api.sent("DELETE", "events/conf27") == []


async def test_product_can_be_created_with_the_required_first_variation(app, api):
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": True})
    api.route("POST", "events/conf27/items", {"id": 3, "variations": [{"id": 4, "value": "Adult"}]})
    result = await invoke(app, "create_product", event="conf27", name="Admission", first_variation="Adult")
    assert api.sent("POST", "events/conf27/items")[0]["variations"] == [{"value": "Adult"}]
    assert result["created"]["variations"][0]["id"] == 4


async def test_question_gets_a_unique_identifier_when_omitted(app, api):
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": True})
    api.route("POST", "events/conf27/questions", {"id": 3})
    await invoke(app, "create_question", event="conf27", question="Test question", type="S")
    identifier = api.sent("POST", "events/conf27/questions")[0]["identifier"]
    assert identifier.startswith("agent-") and len(identifier) > 10


async def test_variation_quota_requires_parent_product_before_posting(app, api):
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": True})
    with pytest.raises(ValidationError, match="parent product"):
        await invoke(app, "create_quota", event="conf27", name="Test quota", variations=[4], size=10)
    assert api.sent("POST", "events/conf27/quotas") == []


def test_masking_covers_settings_unknown_text_and_non_string_answers():
    raw = {
        "settings": {"mail_bcc": "alice@example.org", "plugin_note": "Contact alice@example.org"},
        "answer": 36123456789,
        "phone": 36123456789,
        "answers": ["private response", 42],
    }
    masked = repr(redact(raw))
    assert "alice@example.org" not in masked
    assert "36123456789" not in masked
    assert redact({"answer": ["private response", 42]}) == {"answer": ["***", "***"]}


async def test_routing_settings_cannot_be_read_even_in_full_mode(make_app, api):
    app = make_app(PII_MODE="full")
    api.route("GET", "events/conf27/settings", {"mail_bcc": "alice@example.org", "smtp_password": "dummy"})
    for key in ("mail_bcc", "smtp_password", "payment_stripe_secret_key"):
        with pytest.raises(ValidationError, match="not agent-readable"):
            await invoke(app, "get_event_settings", event="conf27", keys=[key])


async def test_rejections_are_audited_and_state_is_owner_only(app, api, monkeypatch):
    api.route("GET", "events/conf27", {"slug": "conf27", "live": False, "testmode": True})
    api.page("GET", "events/conf27/orders", [])
    action_id = (await invoke(app, "delete_event", event="conf27"))["pending_action_id"]
    monkeypatch.setattr("pretix_agent_mcp.cli.load", lambda config_file=None: app.cfg)
    monkeypatch.setattr("pretix_agent_mcp.cli.build_app", lambda cfg: app)
    assert main(["reject", action_id]) == 0
    records = [json.loads(line) for line in app.cfg.audit_log.read_text().splitlines()]
    assert any(r["event"] == "rejected" and r["pending_action_id"] == action_id for r in records)
    assert stat.S_IMODE(app.cfg.audit_log.stat().st_mode) == 0o600
    assert stat.S_IMODE(app.cfg.state_db.stat().st_mode) == 0o600
