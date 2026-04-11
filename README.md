<p align="center">
  <a href="https://www.odoo.com"><img src="assets/odoo-logo.svg" alt="Odoo" height="60"/></a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://modelcontextprotocol.io"><img src="assets/mcp-logo.svg" alt="Model Context Protocol" height="60"/></a>
</p>

<h1 align="center">odoo-mcp-pro</h1>

<p align="center">
  AI connector for Odoo ERP -- talk to your business data using natural language.<br/>
  Search, create, update, and manage records -- just ask.
</p>

<p align="center">
  <a href="https://github.com/pantalytics/odoo-mcp-pro/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg" alt="License: PolyForm Noncommercial"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"/></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-compatible-green.svg" alt="MCP Compatible"/></a>
  <a href="https://www.odoo.com/documentation/19.0/developer/reference/external_api.html"><img src="https://img.shields.io/badge/Odoo-14--19+-714b67.svg" alt="Odoo 14-19+"/></a>
  <a href="https://oauth.net/2.1/"><img src="https://img.shields.io/badge/OAuth-2.1-orange.svg" alt="OAuth 2.1"/></a>
  <img src="https://img.shields.io/badge/Status-Free%20Beta-brightgreen.svg" alt="Free Beta"/>
</p>

> **Free Beta** -- odoo-mcp-pro is currently free during the beta period. [Sign up at pantalytics.com](https://pantalytics.com/en/apps/odoo-mcp-server)

<p align="center">
  <img src="docs/ai-grid@2x.png" alt="Odoo connected to Claude, OpenAI, Gemini, Copilot, Mistral via MCP" width="500"/>
</p>

---

## The idea

Odoo is powerful. AI is powerful. Together they're better.

odoo-mcp-pro is an AI connector for Odoo that uses MCP (Model Context Protocol) -- an open standard that lets AI assistants talk to external systems. It connects your AI assistant to your Odoo ERP, so you can use natural language as an interface to your business data. Not to replace Odoo's UI -- but to give you a second interface that's faster for many tasks. Works with Claude, ChatGPT, Cursor, Windsurf, and any other MCP-compatible AI tool.

> **"Show me all unpaid invoices over 5,000 EUR from Q4"** -- your AI queries your Odoo instance directly and returns the results.

<p align="center">
  <img src="docs/demo.gif" alt="Demo of odoo-mcp-pro" width="800"/>
</p>

**Use the interface that fits the task.** Complex configuration? Use the Odoo UI. Quick data lookup, bulk questions, or creating records on the fly? Just ask your AI.

## What you can do

- *"Find all contacts in Amsterdam with open quotations"*
- *"Create a lead for Acme Corp, expected revenue 50k EUR"*
- *"Which sales orders from last month don't have a delivery yet?"*
- *"What fields does the sale.order model have?"*
- *"Update the expected closing date on opportunity #42 to next Friday"*

Works with any Odoo model -- sales, invoices, contacts, inventory, CRM, HR, you name it.

## Get started

### Hosted (recommended)

We run the server for you. No installation, no Docker, no infrastructure.

1. **[Sign up at pantalytics.com](https://pantalytics.com/en/apps/odoo-mcp-server)**
2. Log in and enter your Odoo URL + API key ([how to generate one](SETUP.md#generating-an-odoo-api-key))
3. Add the MCP server to your AI tool (Claude, ChatGPT, Cursor, etc.)
4. Start asking questions

Your data stays in Odoo -- the server is a stateless proxy. API keys are encrypted at rest.

### Self-hosted

Deploy on your own infrastructure with Docker Compose, Postgres, Zitadel, and Caddy. Full control, same features.

See [SETUP.md](SETUP.md) for the deployment guide.

## How it works

odoo-mcp-pro is an Odoo connector that implements [MCP (Model Context Protocol)](https://modelcontextprotocol.io) -- an open standard that lets AI assistants call external tools. It exposes 6 tools that your AI can call based on your questions:

| Tool | What it does |
|------|-------------|
| `search_records` | Search any model with domain filters, sorting, pagination |
| `get_record` | Fetch a specific record by ID with smart field selection |
| `list_models` | Discover available Odoo models |
| `create_record` | Create a new record in any model |
| `update_record` | Update fields on an existing record |
| `delete_record` | Delete a record |

**Supports Odoo 14-19+** -- uses the JSON/2 API for Odoo 19+ and XML-RPC for older versions. The right protocol is selected automatically.

## Security

- **Odoo is the boss.** All data, permissions, and business logic live in Odoo. Each user's API key determines what they can see and do -- ACLs and record rules apply as normal.
- **Stateless proxy.** The MCP server doesn't store or cache your business data.
- **API keys encrypted at rest** using AES-128 (Fernet). Never exposed to the AI, the browser, or logs.
- **You stay in control.** Revoke your API key in Odoo at any time to instantly cut off access.

## Development

```bash
uv venv --python 3.10
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest tests/ -q
ruff check . && ruff format .
```

See [architecture.md](architecture.md) for technical details and [CLAUDE.md](CLAUDE.md) for coding conventions.

## Contributing

Contributions are welcome. Fork the repo, create a feature branch, run `pytest tests/` and `ruff check .`, then open a PR.

## FAQ

**Which Odoo versions are supported?**
Odoo 14-19+. The server auto-detects whether to use JSON/2 (Odoo 19+) or XML-RPC (14-18). No configuration needed.

**Does it work on my phone?**
Yes -- the hosted version works on Claude mobile (iOS/Android), Claude.ai in any browser, Claude Desktop, Claude Code, and ChatGPT. Local installs (STDIO) only work on the machine where they're installed.

**Is my data safe?**
Your data stays in Odoo. The MCP server is a stateless proxy -- it doesn't store or cache business data. API keys are encrypted at rest with AES-128 (Fernet). Each user's Odoo permissions apply: you can only see and do what your Odoo role allows.

**I get "Access denied" on all models**
This usually means your Odoo API key doesn't have the right permissions. Try:
1. **Regenerate your API key** in Odoo (Settings > Users > API Keys) and update it in `/admin/setup`
2. Make sure your Odoo user has at least read access to the models you want to query
3. If you're on Odoo.sh, verify your subscription plan supports the JSON/2 API

**I get "Authentication required" or "invalid_token"**
This means the OAuth connection between your AI tool and the MCP server failed. Try disconnecting and reconnecting the MCP server in your AI tool's settings.

**Do I need to set ODOO_DB?**
Only if you self-host Odoo with multiple databases. Odoo.sh and Odoo Online don't need it -- the hostname determines the database.

## License

[PolyForm Noncommercial 1.0.0](LICENSE) -- free for personal and noncommercial use. Commercial use requires a separate license from [Pantalytics](https://pantalytics.com).

## For Odoo Implementation Partners

**odoo-mcp-pro** is licensed under [PolyForm Noncommercial 1.0.0](LICENSE). Using this software to provide commercial services to your clients -- including hosting, reselling, bundling, or offering it as part of your Odoo implementation services -- is a violation of the license and will be enforced. We actively monitor for unauthorized commercial use and will pursue legal action where necessary.

**Want to offer AI-powered Odoo to your clients?** We run a Partner Program with a referral commission. You recommend odoo-mcp-pro to your end users, they sign up through your referral link, and you earn a recurring fee. No hosting or maintenance on your side.

Interested? Contact [rutger@pantalytics.com](mailto:rutger@pantalytics.com) for details.

## Built by Pantalytics

**odoo-mcp-pro** is built and maintained by [Pantalytics](https://pantalytics.com), an Odoo implementation partner based in Utrecht, Netherlands.

Originally forked from [mcp-server-odoo](https://github.com/ivnvxd/mcp-server-odoo) by Andrey Ivanov (originally MPL-2.0).

---

<sub>Odoo is a registered trademark of <a href="https://www.odoo.com">Odoo S.A.</a> The MCP logo is used under the <a href="https://github.com/modelcontextprotocol/modelcontextprotocol">MIT License</a>. This project is not affiliated with or endorsed by Odoo S.A. or Anthropic.</sub>
