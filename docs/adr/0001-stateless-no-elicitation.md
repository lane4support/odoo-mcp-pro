# ADR 0001: Stateless HTTP, no MCP elicitation for wizard follow-ups

- Status: Accepted
- Date: 2026-06-17
- Deciders: Rutger
- Scope: `execute_method` + the wizard follow-up layer (`tools/wizards.py`,
  `tools/methods.py`) and the Streamable HTTP transport config in `server.py`.

## Context

Some Odoo business methods do not complete in one call: they return a wizard
that asks a follow-up question (e.g. `stock.picking.button_validate` asks
whether to create a backorder; `account.move.action_register_payment` asks for
journal/amount/date). We need a way to get that answer.

MCP has a feature for exactly this: **elicitation**, where the server pauses a
tool call and asks the client (which may show a form to a human, or have an
agent answer) before continuing.

Our transport is **Streamable HTTP, stateless** (`stateless_http=True`,
`json_response=True`). Stateless is a deliberate, hard-won choice: any replica
can serve any request, so blue/green deploys do not drop client connections
with "No transport found for sessionId". Making the server stateful brought
exactly that connection churn back.

## What we tested

Against the live staging server we measured the two directions of elicitation:

- With `json_response=True`: the server cannot send the elicitation request at
  all (no stream). The tool call hangs until the client times out.
- With `json_response=False` (streaming on, still stateless): the elicitation
  request **does** reach the client. But the client's **answer** (a separate
  POST) cannot be routed back to the suspended call, because there is no session
  to correlate it. The call still times out.

Conclusion: completing an elicitation over HTTP needs a **stateful session**
(`Mcp-Session-Id`) to route the answer back. Stateless can send the question but
not receive the answer. You cannot have "stateless + live elicitation over HTTP"
at the same time. (See the MCP transports spec, 2025-06-18.)

## Decision

1. Keep the HTTP transport **stateless** (`stateless_http=True`,
   `json_response=True`). Connection stability wins: an unstable connection is
   churn. This outranks a richer interaction model for now.
2. Do **not** use MCP elicitation for wizard follow-ups, on any transport
   (including stdio, where it would technically work). One uniform, stateless
   path is simpler than two and behaves the same in chat, agents, and n8n.
3. Wizard follow-ups use a **two-step, stateless flow**:
   - Call `execute_method` without a `decision`. A known wizard returns its
     fields in `followup`.
   - Read the fields, re-call `execute_method` with `decision` filled in. The
     tool then drives Odoo's own wizard to completion.

## Consequences

- A wizard action takes two tool calls instead of one. The first is read-only
  discovery; the second performs the action. No live back-and-forth is needed,
  so it works identically for a human in chat, an autonomous agent, and an n8n
  flow.
- No elicitation code to maintain (`_try_elicit`, the `ctx`/Context plumbing,
  the McpError/anyio handling) - removed.
- We lose the live "form pops up mid-call" experience. That is acceptable: the
  fields are still discoverable via `followup`, just in a separate step.

## Revisit when

We want a richer, interactive experience (live forms, progress streaming,
sampling). That implies either session affinity at the load balancer (route by
`Mcp-Session-Id`) or a different transport, plus `json_response=False`. Revisit
the stateless decision then, weighing the richer UX against the deploy-time
connection churn that made us choose stateless in the first place.
