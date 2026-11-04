# Desktop client connection

The production service must be running and verified before enabling these clients.
Use the runtime's private HTTPS endpoint, or loopback HTTP only for a same-machine
deployment. A same-user local service does not isolate credentials or approval controls
from an unrestricted coding agent; make that deployment choice explicitly.

`client.py` uses the existing locked MCP SDK. It supports:

- `--headers`: JSON authentication output for Codex's `http_headers_helper` or Claude
  Code's `headersHelper`. Only the client should consume this mode; do not print it in
  terminals, logs, chat or diagnostics.
- `--stdio`: a transparent MCP STDIO/Streamable-HTTP relay for Claude Desktop. It carries
  requests, responses, errors and cancellation notifications without adding tools or
  exposing approval commands.
- `--check`: credential-free discovery summary for deployment verification.

The local client profile contains exactly these non-secret fields:

```json
{
  "url": "https://mcp-host.example-tailnet.ts.net/mcp",
  "keychain_service": "pretix-mcp-client",
  "keychain_account": "desktop"
}
```

Store the client bearer credential in the referenced macOS Keychain item. The upstream
Pretix token belongs on the trusted service runtime, not in client configuration. Keep
real profiles outside Git, with owner-only permissions. Neither credential belongs in
command-line arguments. The helper captures Keychain output internally and emits only
the protocol output required by the requesting client.

Use absolute executable, script and profile paths in client configurations. The relay
can be launched directly as `ABSOLUTE_PYTHON ABSOLUTE_CLIENT_SCRIPT --profile
ABSOLUTE_PROFILE --stdio`; it does not need to install dependencies or update itself.

Codex supports a Streamable HTTP `url` with `http_headers_helper`. Claude Code supports
HTTP `url` with `headersHelper` in its user-scoped MCP configuration. Claude Desktop's
local MCP configuration can launch the STDIO relay. Cloud-brokered Claude connectors
require public reachability and therefore cannot reach this private Tailscale endpoint;
they are a different deployment.

Before editing client configurations, record the previous entry and file hash and define
rollback. Preserve all unrelated MCP servers and settings. Verify authentication,
discovery, and a synthetic create/readback/delete on the dedicated test event before
using production writes. Never test writes by changing live inventory merely to see if
access works. Restart only the affected MCP connection where supported; otherwise the
client needs a fresh session after configuration changes.

Production access starts with named Foundation events, general event/catalog/date/quota/
voucher/order operations as required, and explicit high-risk controls. Keep
`MCP_AUTO_APPROVE` empty. Do not grant team administration or payment-routing changes.
The example in `profiles/write-production.json` is inactive until a trusted operator
replaces its example event names and supplies the service credentials securely.

## This Mac: local runtime

`service.py --config ABSOLUTE_SERVER_PROFILE serve` runs the loopback HTTP service.
The profile's `keychain` object names `service`, `api_account` and `client_account`;
all remaining settings use the normal server configuration schema. Raw credentials
in the profile are refused. The runtime ignores ambient permission environment
variables and requires `127.0.0.1`, named events, PII redaction, no automatic approvals
and the verified `https://pretix.eu` upstream.

`bootstrap.py` is run as a module from the source checkout. It receives a newly
authorized Pretix token once through a nonce-protected loopback form, validates that
its visible events exactly match the profile, then creates two new login Keychain
items (upstream API credential and generated client bearer). Existing items are
never silently replaced. The helper reads Keychain through Security.framework;
credentials never enter shell arguments. Do not print or copy these items into
diagnostic output. The generic-password APIs are deprecated by Apple but remain
supported on this Mac; no additional dependency is installed for Keychain access.

The LaunchAgent uses a small immutable Git export for source and the existing pinned
Python environment. Keep that environment until the deployment is replaced. A user
LaunchAgent starts after login and restarts after failure; it is unavailable while
the Mac sleeps or is offline. No public listener or tunnel is needed for local clients.
Other unrestricted processes under the same macOS user can reach the source,
credentials and operator controls. This is an accepted local deployment tradeoff,
not an isolation boundary.

Operator commands use the same executable, `service.py` and profile:

```text
service.py --config ABSOLUTE_SERVER_PROFILE pending
service.py --config ABSOLUTE_SERVER_PROFILE approve ACTION_ID --run
service.py --config ABSOLUTE_SERVER_PROFILE reject ACTION_ID
```

Review the preview before approval. Normal writes on live, non-test events escalate
to pending approval as well as the always-high-risk tools. Clients can propose and
execute approved actions, but have no MCP tool to approve them. Local unrestricted
coding agents can still invoke these operator commands through shell access.

`python -m deployment.verify` checks missing/incorrect authentication, authorized
event visibility, denied scope, HTTP/STDIO discovery, and create/update/readback/
operator-approved cleanup of one inactive product on `mcp-test-20261104`. It writes a
credential-free receipt with the fixture ID if interrupted. It never changes a live
product, creates an order, sends an email or moves money.

Before enabling clients, retain a targeted rollback receipt: original Pretix entries
and configuration hashes, exact new entry/block, LaunchAgent path and release path.
Stop with `launchctl bootout gui/UID/LABEL`; remove only this deployment's client
entry, preserving concurrent unrelated changes. Revoking its named Pretix API token
in the scoped team immediately cuts off upstream access. Keep audit/database and
Keychain items until their operational/rollback purpose has been reviewed.
