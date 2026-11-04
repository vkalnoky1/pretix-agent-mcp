FROM python:3.13.16-slim@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f

# The audit log and the pending-approval database live in /state — mount it, or an
# approved-but-not-executed action disappears when the container restarts.
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY requirements-runtime.txt requirements-build.txt ./
COPY pretix_agent_mcp ./pretix_agent_mcp
RUN pip install --no-cache-dir --require-hashes -r requirements-build.txt -r requirements-runtime.txt \
    && pip install --no-cache-dir --no-build-isolation --no-deps . \
    && groupadd --gid 10001 agent && useradd --uid 10001 --gid agent --no-create-home agent \
    && mkdir -p /state && chown agent:agent /state

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    STATE_DB=/state/pending-actions.sqlite3 \
    AUDIT_LOG=/state/audit.jsonl
EXPOSE 8765
USER 10001:10001

# Configuration comes from the environment; nothing secret is baked into the image.
# Publish the port to 127.0.0.1 only; Tailscale Serve on the host is the production ingress.
ENTRYPOINT ["pretix-agent-mcp"]
CMD ["serve"]
