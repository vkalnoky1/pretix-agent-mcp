"""Keychain-backed authentication and a transparent STDIO/HTTP relay.

Never invoke --headers in a terminal: only an MCP client's header helper should
consume its output. --check prints a credential-free discovery summary instead.
The relay carries MCP messages, not raw Pretix REST access or approval commands.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.server.stdio import stdio_server
from mcp_types import CLIENT_CAPABILITIES_META_KEY, LATEST_PROTOCOL_VERSION, PROTOCOL_VERSION_META_KEY

from pretix_agent_mcp.keychain import read


@dataclass(frozen=True)
class ClientProfile:
    url: str
    keychain_service: str
    keychain_account: str


def load_profile(path: Path) -> ClientProfile:
    raw = json.loads(path.read_text())
    profile = ClientProfile(**raw)
    parsed = urlsplit(profile.url)
    local = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if (
        parsed.scheme != "https"
        and not (parsed.scheme == "http" and local)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/mcp"
    ):
        raise ValueError("expected an HTTPS or loopback MCP endpoint without embedded credentials")
    if not profile.keychain_service or not profile.keychain_account:
        raise ValueError("missing Keychain item reference")
    return profile


def load_token(profile: ClientProfile) -> str:
    token = read(profile.keychain_service, profile.keychain_account).strip()
    if len(token) < 24 or not token.isascii() or any(c.isspace() for c in token):
        raise RuntimeError("MCP credential unavailable in Keychain")
    return token


async def forward(source, destination):
    async for message in source:
        if isinstance(message, Exception):
            raise RuntimeError("MCP transport failed") from None
        await destination.send(message)


async def relay(profile: ClientProfile, token: str):
    async with create_mcp_http_client(headers={"Authorization": "Bearer " + token}) as http:
        async with streamable_http_client(profile.url, http_client=http) as (remote_read, remote_write):
            async with stdio_server() as (local_read, local_write):
                async with asyncio.TaskGroup() as group:
                    jobs = [
                        group.create_task(forward(local_read, remote_write)),
                        group.create_task(forward(remote_read, local_write)),
                    ]
                    done, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    for task in done:
                        task.result()


async def check(profile: ClientProfile, token: str) -> dict:
    """Discover through the same private endpoint without printing the credential."""
    meta = {PROTOCOL_VERSION_META_KEY: LATEST_PROTOCOL_VERSION, CLIENT_CAPABILITIES_META_KEY: {}}
    headers = {
        "Authorization": "Bearer " + token,
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": LATEST_PROTOCOL_VERSION,
        "mcp-method": "tools/list",
    }
    async with create_mcp_http_client(headers=headers) as client:
        response = await client.post(
            profile.url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}
        )
        response.raise_for_status()
        tools = response.json()["result"]["tools"]
    return {"connected": True, "tool_names": sorted(t["name"] for t in tools)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--headers", action="store_true")
    mode.add_argument("--stdio", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        profile = load_profile(args.profile)
        token = load_token(profile)
        if args.headers:
            print(json.dumps({"Authorization": "Bearer " + token}))
        elif args.check:
            print(json.dumps(asyncio.run(check(profile, token))))
        else:
            asyncio.run(relay(profile, token))
        return 0
    except Exception as exc:
        print(f"Pretix MCP connection failed ({type(exc).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
