"""Receive the specifically authorized token locally and store it in Keychain.

Only safe status summaries are printed. No raw credential enters argv or files.
Run from the repository with `python -m deployment.bootstrap --config PATH`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
from pathlib import Path

import httpx

from pretix_agent_mcp.keychain import add, read
from scripts.verify_test_writes import receive_token


def main():
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.config.read_text())
    refs = raw["keychain"]
    token = receive_token(0, production=True)
    with httpx.Client(
        base_url="https://pretix.eu/api/v1/organizers/kalnoky/",
        headers={"Authorization": "Token " + token},
        follow_redirects=False,
        timeout=30,
    ) as client:
        response = client.get("events/")
        response.raise_for_status()
        data = response.json()
        expected = set(raw["PRETIX_EVENT_ALLOWLIST"])
        if data.get("next") or {e["slug"] for e in data["results"]} != expected:
            raise RuntimeError("API event scope differs from the approved named event list")
        event = client.get("events/mcp-test-20261104/")
        event.raise_for_status()
        if not event.json()["testmode"] or event.json()["live"]:
            raise RuntimeError("validation event must remain disabled and in test mode")
    bearer = secrets.token_hex(32)
    add(refs["service"], refs["api_account"], token)
    add(refs["service"], refs["client_account"], bearer)
    if read(refs["service"], refs["api_account"]) != token:
        raise RuntimeError("API credential readback failed")
    if read(refs["service"], refs["client_account"]) != bearer:
        raise RuntimeError("client credential readback failed")
    print(json.dumps({"keychain_saved": True, "event_scope_verified": sorted(expected)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Bootstrap failed ({type(exc).__name__}); inspect token scope before retrying.", file=sys.stderr
        )
        sys.exit(1)
