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
