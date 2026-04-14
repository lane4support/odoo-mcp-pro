# CLAUDE.md -- Instructions for Claude Code

## What this project is

**odoo-mcp-pro** -- an open source MCP server connecting AI to Odoo ERP.
Supports Odoo 14-19+, stdio and streamable-http transport, OAuth 2.1.

This is the **public** package. The admin panel, billing, and deploy infrastructure
live in the private repo: `pantalytics/odoo-mcp-pro-admin`.

## Design principles

1. **Odoo + AI, samen sterker** -- don't replace Odoo, make it more accessible via AI
2. **Use the interface that fits** -- Odoo UI for complex config, Claude for quick queries and data entry
3. **Odoo is the boss** -- all data, permissions, and business logic live in Odoo; MCP server is a stateless proxy
4. **No fallbacks** -- explicit configuration or clear errors, never guess
5. **Open core** -- public package works standalone, private package adds SaaS features

## Key architecture facts

- Connection factory: `OdooJSON2Connection` (Odoo 19+) / `OdooConnection` (Odoo 14-18, XML-RPC)
- ConnectionRegistry caches connections per user (30 min TTL, multi-tenant only)
- `odoo_knowledge.py` provides Odoo domain knowledge via MCP server instructions
- Without `DATABASE_URL`: single-tenant mode (one Odoo instance from env vars)
- With `DATABASE_URL`: multi-tenant mode (requires odoo-mcp-pro-admin package)

## JSON/2 API key points

- Endpoint: `POST /json/2/{model}/{method}`
- Auth: `Authorization: Bearer <api_key>` header
- Database: `X-Odoo-Database: <db>` header
- Body: flat JSON with named args, `ids` and `context` are top-level keys
- Create/write use `vals` (not `values`)
- Responses are raw JSON (no RPC envelope)
- Errors return proper HTTP status codes (401, 403, 404, 422, 500)

## Development

```bash
uv venv --python 3.10
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest tests/ -x -q         # unit tests (mocked), stop on first failure
```

## Conventions

- Follow existing code style (ruff configured in pyproject.toml)
- Keep JSON/2 and XML-RPC clients in separate files -- do not merge them
- Both connection classes must satisfy `OdooConnectionProtocol`
- Shared exceptions live in `exceptions.py`
- No new dependencies without discussion (httpx already available)
- No hardcoded fallbacks -- explicit config or clear errors
- Self-hosted Odoo requires explicit database name (no auto-detection)
- Odoo.sh determines database by hostname (no database name needed)

## Key files

| File | Role |
|------|------|
| `server.py` | Factory pattern, OAuth wiring, FastMCP setup |
| `tools.py` | MCP tools (search, create, update, delete, import) |
| `resources.py` | MCP resources (URI-based) |
| `schemas.py` | Pydantic result models |
| `odoo_json2_connection.py` | JSON/2 client (httpx, Odoo 19+) |
| `odoo_connection.py` | XML-RPC client (stdlib, Odoo 14-18) |
| `connection_protocol.py` | Protocol class for connection interface |
| `registry.py` | ConnectionRegistry -- maps users to Odoo connections |
| `oauth.py` | ZitadelTokenVerifier -- token introspection with caching |
| `odoo_knowledge.py` | Odoo domain knowledge (server instructions) |
| `config.py` | OdooConfig dataclass |
| `usage.py` | Usage tracking stub (full version in admin package) |
| `access_control.py` | Odoo ACL checks via check_access_rights |
