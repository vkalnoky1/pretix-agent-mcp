"""Verify the deployed endpoint and Desktop relay using one disposable test product.

Only mcp-test-20261104 is writable here. No customer, order, email or payment
operation is performed. The operator-side approval is limited to this run's new
synthetic product; no other pending action is approved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from deployment.client import load_profile, load_token
from deployment.service import load_service
from pretix_agent_mcp.server import build_app

EVENT = "mcp-test-20261104"


def unpack(result):
    if getattr(result, "isError", False):
        raise RuntimeError("MCP verification tool failed")
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads("".join(c.text for c in result.content if c.type == "text"))


async def verify(args, receipt):
    profile = load_profile(args.client)
    token = load_token(profile)
    cfg = load_service(args.config)
    app = build_app(cfg)
    checks = receipt["checks"]
    async with httpx.AsyncClient() as http:
        response = await http.get(profile.url)
        assert response.status_code == 401
        response = await http.get(profile.url, headers={"Authorization": "Bearer " + "wrong" * 8})
        assert response.status_code == 401
    checks.append("missing and incorrect bearer credentials rejected")

    async with create_mcp_http_client(headers={"Authorization": "Bearer " + token}) as http:
        async with streamable_http_client(profile.url, http_client=http) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                assert {"create_product", "delete_product", "execute_pending_action"} <= tools
                assert not {"create_event", "clone_event", "delete_event"} & tools
                receipt["tool_count"] = len(tools)
                checks.append("authenticated HTTP initialization and tool discovery")
                visible = unpack(await session.call_tool("list_events", {"limit": 50}))
                assert {e["slug"] for e in visible["results"]} == set(cfg.event_allowlist)
                checks.append("all eight authorized events readable")
                denied = await session.call_tool("get_event", {"event": "custom-test-kp"})
                assert denied.isError
                checks.append("out-of-scope event rejected by MCP")
                event = unpack(await session.call_tool("get_event", {"event": EVENT}))
                assert event["testmode"] and not event["live"] and not event["is_public"]
                checks.append("validation event remains hidden, disabled and in test mode")
                label = "MCP deployment verification " + secrets.token_hex(4)
                product = unpack(
                    await session.call_tool(
                        "create_product",
                        {
                            "event": EVENT,
                            "name": label,
                            "default_price": "1.00",
                            "active": False,
                        },
                    )
                )["created"]
                receipt["created_product"] = product["id"]
                checks.append("test product created through deployed HTTP endpoint")

                # Exercise the exact executable/profile/relay used by Claude Desktop.
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        str(args.release / "deployment/client.py"),
                        "--profile",
                        str(args.client),
                        "--stdio",
                    ],
                )
                async with stdio_client(parameters) as relay_streams:
                    async with ClientSession(*relay_streams) as desktop:
                        await desktop.initialize()
                        assert {t.name for t in (await desktop.list_tools()).tools} == tools
                        actual = unpack(
                            await desktop.call_tool(
                                "get_product",
                                {
                                    "event": EVENT,
                                    "item_id": product["id"],
                                },
                            )
                        )
                        assert actual["id"] == product["id"] and actual["name"] == label
                        checks.append("STDIO relay initialized, discovered tools and read back fixture")
                        changed = unpack(
                            await desktop.call_tool(
                                "update_product",
                                {
                                    "event": EVENT,
                                    "item_id": product["id"],
                                    "default_price": "2.00",
                                },
                            )
                        )
                        assert changed["updated"]["default_price"] == "2.00"
                        checks.append("test product updated through Desktop STDIO relay")

                proposed = unpack(
                    await session.call_tool(
                        "delete_product",
                        {
                            "event": EVENT,
                            "item_id": product["id"],
                        },
                    )
                )
                assert proposed["status"] == "awaiting_approval"
                action_id = proposed["pending_action_id"]
                action = app.pending.get(action_id)
                assert action.tool == "delete_product"
                assert action.args == {"event": EVENT, "item_id": product["id"]}
                checks.append("synthetic deletion waits for operator approval")
                app.pending.decide(action_id, "approved")
                app.audit.write(
                    "approved",
                    tool=action.tool,
                    args=action.args,
                    pending_action_id=action.id,
                    outcome="approved",
                )
                unpack(await session.call_tool("execute_pending_action", {"pending_action_id": action_id}))
                receipt["removed_product"] = product["id"]
                missing = await session.call_tool("get_product", {"event": EVENT, "item_id": product["id"]})
                assert missing.isError
                checks.append("only this run's fixture approved, deleted and confirmed absent")
    await app.pretix.aclose()
    receipt["status"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    receipt = {"status": "running", "checks": [], "event": EVENT}
    try:
        asyncio.run(verify(args, receipt))
    except Exception as exc:
        receipt.update(status="failed", error_class=type(exc).__name__)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
