# Write-capable hardened fork

Based on upstream commit `558e1ef13a56dc03ef0b9a83a81c99a44467165e`.
The fork retains the upstream MIT license and purpose-built MCP tools.

## Changes

- Approval expiry is checked atomically when executing, including actions already approved.
- Tool-name allowlists now narrow capability classes. They cannot bypass a read-only switch.
- `PRETIX_TEST_MODE_ONLY=true` requires an explicit event allowlist, refuses production-event
  writes, and refuses publishing even after approval or auto-approval configuration.
- The current safety profile is rechecked before approved actions execute.
- Ordinary writes still execute directly on test-mode events. Production live-event guards
  and out-of-band approval for high-risk operations remain in place.
- Known email settings, email-shaped values in unknown fields, and numeric/boolean personal
  values are masked. Routing/payment credential settings cannot be retrieved by name.
  Masking remains data minimization, not a guarantee of anonymity for arbitrary free text.
- Pending-action databases and audit files are owner-only (`0600`). Rejections are audited.
- Runtime and build dependency versions/hashes are recorded in `uv.lock` and the two
  `requirements-*.txt` exports. Direct runtime dependencies and Hatchling are pinned.
- Docker builds this source, uses a digest-pinned Python image and hash-checked dependencies,
  and runs as UID 10001. The example no longer pulls a mutable prebuilt MCP image.

## Install and verify

Use Python 3.11–3.13 and uv. For development:

```sh
make setup
make ci
```

`make setup` first installs the locked build tools, then installs the project without
build isolation. This avoids resolving a separate, unlocked build environment.
Do not use the upstream editable-pip instructions for the hardened deployment.

When changing dependencies, regenerate and audit both exports:

```sh
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements-runtime.txt
uv export --locked --only-group build --no-emit-project --format requirements-txt --output-file requirements-build.txt
```

## First write evaluation

1. Create one dedicated event in the Pretix UI. Keep it in test mode, shop disabled and
   hidden from public lists. Never reuse an event belonging to another integration.
2. Create a dedicated team restricted to that event. Permit event settings, tax rules,
   series dates, products/quotas/questions, orders and vouchers as needed for evaluation.
   Do not grant all events, organizer event creation, team administration, customer-account
   access, payment-setting changes or full-event cancellation.
3. Use `profiles/write-test.json`, replace its example organizer/event names, and supply
   `PRETIX_API_TOKEN` and `MCP_BEARER_TOKEN` through the trusted runtime's secret mechanism.
   Never commit real credentials or configurations. The test-event token must itself lack
   access to production events; the MCP allowlist is an additional boundary.
4. Run `scripts/verify_test_writes.py` with the locked environment. Its `--help` lists the
   required arguments. It accepts the token once through a nonce-protected loopback form,
   keeps it in memory, checks HTTP authentication and upstream event restrictions, and
   exercises real create/update/readback/delete operations through the real MCP ASGI app.
5. The verifier creates only synthetic catalog/date/voucher/check-in fixtures and removes
   them through the high-risk approval flow. It makes no order, sends no customer email,
   publishes no event and moves no money. It verifies the event remains hidden, disabled
   and in test mode and compares final resource counts with the baseline.
6. Review the credential-free JSON receipt. If cleanup fails, inspect its exact fixture IDs;
   do not delete unrelated objects. Revoke the temporary token after verification.

The verifier's approval calls are trusted operator-side test code, not an agent-accessible
MCP approval tool. Do not run its operator controls where an untrusted agent can use them
to approve production actions.

## Production preparation

Use a separate trusted runtime that Codex/Claude cannot administer through shell or the
Docker socket. A container on the coding agent's own unrestricted host does not establish
an approval or credential isolation boundary.

Create a separately scoped production team only after the test receipt is reviewed.
Choose named events and the necessary operational writes. Keep refunds, cancellations,
deletions and publishing controlled individually. Keep `MCP_AUTO_APPROVE` empty until a
specific operation has been deliberately authorized. Do not disable test-only mode on
the test configuration or broaden its token as a shortcut.

Public HTTP exposure remains unsupported. Use loopback for local evaluation and the
upstream private-network deployment model for a separately trusted service.

## Storage

Source history belongs in Git. Runtime secrets/configuration, state, audit logs and
verification scratch must stay outside tracked files. `work/` is ignored and disposable
only after its owner verifies that no process needs it and no failed-fixture evidence is
unique. Retain final credential-free verification receipts separately.
