Connect Claude AI to your Odoo 19 database in 5 minutes -- AI connector for Odoo via MCP

Tags: odoo19, api, json2, integration, ai, claude, mcp, connector, odoo-connector

Hi everyone,

We built an AI connector for Odoo that lets you talk to your database in plain English through Claude AI. Ask questions like "show me all unpaid invoices over 5,000 EUR from Q4" and get instant answers -- no exports, no filters, no domain syntax.

It's called **odoo-mcp-pro** and it's free to use: https://github.com/pantalytics/odoo-mcp-pro


## What it looks like in practice

You type in Claude:

> "Which sales orders from last month don't have a delivery yet?"

Claude figures out the right Odoo domain filters, queries your database via the JSON/2 API, and gives you the answer. It works for any model -- sales, invoices, contacts, inventory, CRM leads, you name it.

More examples:

- "Find all contacts in Amsterdam with open quotations"
- "Create a lead for Acme Corp, expected revenue 50k"
- "What fields does the sale.order model have?"
- "Update the expected closing date on opportunity #42 to next Friday"


## How it works

odoo-mcp-pro is an Odoo connector that uses MCP (Model Context Protocol) -- an open standard by Anthropic that lets AI assistants call external tools. The connector exposes 6 tools (search, get, create, update, delete, list models) that Claude can call based on your natural language questions.

Under the hood it uses Odoo 19's new JSON/2 API, which means:
- No custom Odoo modules needed
- API key authentication (no passwords flying around)
- Odoo's own ACLs enforce permissions -- users can only see and do what their Odoo role allows

It also supports Odoo 14-18 via XML-RPC, so you don't need to be on the latest version.


## Two ways to use it

### 1. Hosted version (free beta)

We run the server for you. You just:
1. Sign up and enter your Odoo URL + API key
2. Connect Claude.ai to the server
3. Start asking questions

No installation, no Docker, no infrastructure. Your data stays in Odoo -- the server is a stateless proxy. API keys are encrypted at rest.

**Free during beta.** Sign up at: https://pantalytics.com/odoo-mcp-pro

### 2. Self-hosted

Deploy on your own infrastructure with Docker Compose. Full control, same features. Setup guide in the repo.


## Why we built this

We're Pantalytics, an Odoo partner based in Utrecht. We saw our clients spending hours on reporting queries, data lookups, and manual data entry that could be a simple conversation with AI. The JSON/2 API in Odoo 19 made this practical -- clean REST endpoints, proper auth, no custom modules.

We open-sourced it (MPL-2.0, same as Odoo Community) because we think this should be accessible to the whole ecosystem.


## Key features

- **Odoo 14-19 support** -- JSON/2 for Odoo 19+, XML-RPC for older versions
- **Smart field selection** -- returns the most relevant fields instead of overwhelming the AI with 200+ columns
- **Read and write** -- search, create, update, delete records via natural language
- **Odoo permissions** -- each user's API key determines access, just like in the Odoo UI
- **Multi-user** -- hosted version supports teams with individual API keys and OAuth 2.1
- **480+ unit tests** -- thoroughly tested, all mocked


## Getting started

Clone the repo and connect to Claude Code in under 5 minutes:

```
git clone https://github.com/pantalytics/odoo-mcp-pro.git
cd odoo-mcp-pro
uv venv && source .venv/bin/activate
uv pip install -e .
```

See the README for Claude Desktop and Claude.ai setup instructions.


## We'd love your feedback

- Try it out and let us know what works (and what doesn't)
- Star the repo if you find it useful: https://github.com/pantalytics/odoo-mcp-pro
- Issues and PRs welcome
- Questions? Ask here or open a GitHub discussion

Has anyone else been experimenting with AI + Odoo? Curious what approaches others are taking and which workflows benefit most from natural language access.

Cheers,
Rutger
Pantalytics -- Utrecht, Netherlands
