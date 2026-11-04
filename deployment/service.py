"""Mac-only loopback service and local operator approval entry point.

Configuration contains Keychain references, never raw credentials. Ambient role
environment variables cannot expand the configured service's permissions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pretix_agent_mcp.cli import _dispatch
from pretix_agent_mcp.config import ConfigError, load
from pretix_agent_mcp.keychain import read


def load_service(path: Path):
    raw = json.loads(path.read_text())
    if any(k in raw for k in ("PRETIX_API_TOKEN", "MCP_BEARER_TOKEN")):
        raise ConfigError("use Keychain references rather than credentials in files")
    refs = raw["keychain"]
    cfg = load(
        env={
            "PRETIX_API_TOKEN": read(refs["service"], refs["api_account"]),
            "MCP_BEARER_TOKEN": read(refs["service"], refs["client_account"]),
        },
        config_file=path,
    )
    if cfg.host != "127.0.0.1" or not cfg.event_allowlist or cfg.auto_approve:
        raise ConfigError("local deployment requires loopback, named events and manual approvals")
    if cfg.pii_mode != "redacted" or cfg.pretix_base_url != "https://pretix.eu":
        raise ConfigError("local deployment requires redaction and the verified Pretix host")
    return cfg


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("command", choices=["serve", "pending", "tools", "approve", "reject"])
    parser.add_argument("id", nargs="?")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    args.transport = "http"
    if args.command in {"approve", "reject"} and not args.id:
        parser.error("action id required")
    try:
        return _dispatch(args, load_service(args.config))
    except Exception as exc:
        print(f"Pretix MCP service failed ({type(exc).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
