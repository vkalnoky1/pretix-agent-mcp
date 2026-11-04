"""Exercise real MCP writes on ONE hidden, disabled, test-mode Pretix event.

The token is accepted once through a nonce-protected loopback form and held only in
memory. No environment dumps, request bodies, credentials or customer data are logged.
Fixtures are removed through the same MCP approval flow; failures retain a receipt.
Run with the repository's locked environment, from the repository root.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sys
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx
from mcp_types import CLIENT_CAPABILITIES_META_KEY, LATEST_PROTOCOL_VERSION, PROTOCOL_VERSION_META_KEY

from pretix_agent_mcp.config import load
from pretix_agent_mcp.pretix import PretixError
from pretix_agent_mcp.server import build_app, http_app


def receive_token(port: int) -> str:
    """One-shot local transfer; the token is never a command-line argument or file."""
    nonce = secrets.token_urlsafe(24)
    received: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            if self.path != "/" + nonce:
                return self.reply(404, "Unavailable")
            self.reply(
                200,
                "<h1>Pretix test-only verification</h1>"
                "<p>The API token stays in memory and is never written to disk.</p>"
                '<form method="post"><label>Test-only API token '
                '<input name="token" type="password" autocomplete="off" required></label>'
                "<button>Run test-only verification</button></form>",
            )

        def do_POST(self):
            origin = self.headers.get("Origin")
            length = int(self.headers.get("Content-Length", "0"))
            if (
                self.path != "/" + nonce
                or origin != f"http://127.0.0.1:{port}"
                or not 1 <= length <= 1024
                or received
            ):
                return self.reply(403, "Refused")
            token = parse_qs(self.rfile.read(length).decode()).get("token", [""])[0].strip()
            if not token.isascii() or not token.isalnum() or not 20 <= len(token) <= 200:
                return self.reply(400, "Invalid token format")
            received.append(token)
            self.reply(
                200,
                "<h1>Token received in memory</h1><p>Verification is running. You may close this tab.</p>",
            )

    server = HTTPServer(("127.0.0.1", port), Handler)
    port = server.server_port
    server.timeout = 1
    print(f"TOKEN_FORM=http://127.0.0.1:{port}/{nonce}", flush=True)
    deadline = time.monotonic() + 900
    try:
        while not received and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not received:
        raise RuntimeError("token transfer timed out")
    return received.pop()


async def verify(args, token: str, receipt: dict) -> dict:
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg = load(
        env={
            "PRETIX_BASE_URL": args.base_url,
            "PRETIX_API_TOKEN": token,
            "PRETIX_ORGANIZER": args.organizer,
            "PRETIX_EVENT_ALLOWLIST": args.event,
            "PRETIX_TEST_MODE_ONLY": "true",
            "MCP_CAPABILITIES": "read,write,write:high-risk",
            "MCP_BEARER_TOKEN": secrets.token_hex(32),
            "PII_MODE": "redacted",
            "AUDIT_LOG": str(work / "audit.jsonl"),
            "STATE_DB": str(work / "pending.sqlite3"),
        },
        config_file=work / "absent.json",
    )
    app = build_app(cfg)
    receipt.update(event=args.event, checks=[], created=[], removed=[], status="running")
    cleanup = []
    resources = (
        "items",
        "categories",
        "taxrules",
        "subevents",
        "quotas",
        "vouchers",
        "checkinlists",
        "questions",
    )
    baseline = {}

    def checked(name, condition):
        if not condition:
            raise RuntimeError(name)
        receipt["checks"].append(name)
        print("PASS " + name, flush=True)

    asgi = http_app(app)
    async with asgi.inner.router.lifespan_context(asgi.inner):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi), base_url="http://127.0.0.1:8765"
        ) as client:
            sequence = 0

            async def rpc(method, params=None, *, authenticated=True):
                nonlocal sequence
                sequence += 1
                body = dict(params or {})
                body["_meta"] = {
                    PROTOCOL_VERSION_META_KEY: LATEST_PROTOCOL_VERSION,
                    CLIENT_CAPABILITIES_META_KEY: {},
                }
                headers = {
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                    "mcp-protocol-version": LATEST_PROTOCOL_VERSION,
                    "mcp-method": method,
                }
                if authenticated:
                    headers["authorization"] = "Bearer " + cfg.mcp_bearer_token
                if params and params.get("name"):
                    headers["mcp-name"] = params["name"]
                return await client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": sequence, "method": method, "params": body},
                    headers=headers,
                )

            async def tool(name, /, *, expect_error=False, **kwargs):
                kwargs.setdefault("event", args.event)
                response = await rpc("tools/call", {"name": name, "arguments": kwargs})
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result", {})
                failed = bool(payload.get("error") or result.get("isError"))
                if expect_error:
                    checked(name + " rejected", failed)
                    return {}
                if failed:
                    raise RuntimeError("MCP tool failed: " + name)
                if result.get("structuredContent") is not None:
                    return result["structuredContent"]
                return json.loads("".join(c.get("text", "") for c in result.get("content", [])))

            async def remove(name, kwargs):
                proposal = await tool(name, **kwargs)
                checked(name + " requires approval", proposal.get("status") == "awaiting_approval")
                action_id = proposal["pending_action_id"]
                # Trusted operator side of this controlled test, never an MCP approval tool.
                app.pending.decide(action_id, "approved")
                response = await rpc(
                    "tools/call",
                    {"name": "execute_pending_action", "arguments": {"pending_action_id": action_id}},
                )
                result = response.json().get("result", {})
                checked(name + " executed", response.status_code == 200 and not result.get("isError"))
                receipt["removed"].append({"tool": name, **kwargs})

            try:
                event = await app.pretix.get("events", args.event)
                checked(
                    "hidden disabled test-mode event",
                    event.get("testmode") is True
                    and event.get("live") is False
                    and event.get("is_public") is False,
                )
                for resource in resources:
                    rows = await app.pretix.get("events", args.event, resource, params={"page_size": 1})
                    baseline[resource] = rows.get("count")
                receipt["baseline_counts"] = baseline
                checked(
                    "HTTP authentication required",
                    (await rpc("tools/list", authenticated=False)).status_code == 401,
                )
                listed = (await rpc("tools/list")).json()["result"]["tools"]
                checked(
                    "write tools advertised",
                    {"create_product", "create_subevents", "create_voucher"} <= {t["name"] for t in listed},
                )
                await tool("publish_event", expect_error=True)
                await tool(
                    "update_event", event=args.denied_event, location="MCP negative check", expect_error=True
                )
                try:
                    await app.pretix.get("events", args.denied_event)
                except PretixError as exc:
                    checked("Pretix token denies other event", exc.status == 403)
                else:
                    raise RuntimeError("Pretix token is not event-restricted")
                label = "MCP verification " + secrets.token_hex(3)
                tax = (await tool("create_tax_rule", name=label, rate="21.00"))["created"]["id"]
                cleanup.append(("delete_tax_rule", {"tax_rule_id": tax}))
                category = (await tool("create_category", name=label))["created"]["id"]
                cleanup.append(("delete_category", {"category_id": category}))
                item = (
                    await tool(
                        "create_product", name=label, default_price="25.00", category=category, tax_rule=tax
                    )
                )["created"]["id"]
                cleanup.append(("delete_product", {"item_id": item}))
                await tool("update_product", item_id=item, default_price="30.00")
                checked(
                    "product price changed",
                    (await tool("get_product", item_id=item))["default_price"] == "30.00",
                )
                variation = (
                    await tool(
                        "create_product_variation",
                        item_id=item,
                        value="Test variation",
                        default_price="20.00",
                    )
                )["created"]["id"]
                question = (await tool("create_question", question=label, type="S", items=[item]))["created"][
                    "id"
                ]
                cleanup.append(("delete_question", {"question_id": question}))
                date = (
                    (datetime.now(ZoneInfo("Europe/Bucharest")) + timedelta(days=2))
                    .replace(hour=10, minute=0, second=0, microsecond=0)
                    .isoformat()
                )
                dates = await tool(
                    "create_subevents", dates=[date], name=label, active=False, is_public=False
                )
                subevent = dates["created"][0]["id"]
                cleanup.append(("delete_subevent", {"subevent_id": subevent}))
                quota = (
                    await tool("create_quota", name=label, size=10, variations=[variation], subevent=subevent)
                )["created"]["id"]
                cleanup.append(("delete_quota", {"quota_id": quota}))
                await tool("update_quota", quota_id=quota, size=12)
                quotas = await tool("list_quotas", subevent=subevent)
                checked(
                    "quota updated and read back",
                    any(q["id"] == quota and q["size"] == 12 for q in quotas["results"]),
                )
                voucher = (
                    await tool(
                        "create_voucher",
                        item=item,
                        variation=variation,
                        subevent=subevent,
                        price_mode="set",
                        value="0.00",
                        tag=label,
                    )
                )["created"]["id"]
                cleanup.append(("delete_voucher", {"voucher_id": voucher}))
                checkin = (await tool("create_checkin_list", name=label, subevent=subevent))["created"]["id"]
                cleanup.append(("delete_checkin_list", {"checkin_list_id": checkin}))
                receipt["created"] = [{"cleanup_tool": n, **k} for n, k in cleanup]
                checked("catalog date voucher and check-in writes succeeded", len(cleanup) == 8)
                receipt["status"] = "passed"
            except Exception as exc:
                receipt["status"] = "failed"
                receipt["failure_type"] = type(exc).__name__
                # Our RuntimeError messages contain only static labels/tool names.
                if isinstance(exc, RuntimeError) and not isinstance(exc, PretixError):
                    receipt["failure_check"] = str(exc)
            finally:
                receipt["created"] = [{"cleanup_tool": n, **k} for n, k in cleanup]
                for name, kwargs in reversed(cleanup):
                    try:
                        await remove(name, kwargs)
                    except Exception as exc:
                        receipt.setdefault("cleanup_failures", []).append(
                            {"tool": name, **kwargs, "error_type": type(exc).__name__}
                        )
                final = await app.pretix.get("events", args.event)
                checked(
                    "event remains hidden disabled and test-only",
                    final.get("testmode") is True
                    and final.get("live") is False
                    and final.get("is_public") is False,
                )
                for resource in resources:
                    rows = await app.pretix.get("events", args.event, resource, params={"page_size": 1})
                    checked(resource + " fixtures removed", rows.get("count") == baseline.get(resource))
                orders = await app.pretix.get("events", args.event, "orders", params={"page_size": 1})
                checked("no orders created", orders.get("count") == 0)
                await app.pretix.aclose()
    if receipt.get("cleanup_failures"):
        receipt["status"] = "failed"
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--organizer", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--denied-event", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if not args.base_url.startswith("https://") or args.event == args.denied_event:
        parser.error("use HTTPS and a distinct event for the negative read check")
    logging.disable(logging.CRITICAL)
    receipt = {"checks": [], "removed": [], "status": "starting"}
    try:
        asyncio.run(verify(args, receive_token(args.port), receipt))
    except Exception as exc:
        receipt.update(status="failed", failure_type=type(exc).__name__)
    path = Path(args.receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "checks": len(receipt["checks"]),
                "removed": len(receipt["removed"]),
                "receipt": str(path),
            }
        ),
        flush=True,
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
