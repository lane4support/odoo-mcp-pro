# Connection Stability Analysis - Odoo MCP Pro

## Date: 2026-04-11

## Problem Statement
Users (Daniel, Andrew, and others) report recurring issues:
1. "Could not verify email" during Zitadel registration
2. Login callback loops (callback succeeds but session is lost)
3. Claude MCP connector disconnects requiring manual reconnect
4. Intermittent 503 errors during deploys

---

## 1. Login / Session Issues

### What the logs show (last 7 days)
- **65 OAuth callbacks** received
- **63 successful callbacks** (302 redirect)
- **62 successful logins** ("logged in" in logs)
- **1 invalid state** error
- **2 CORS preflight (OPTIONS)** on callback returning 405
- Multiple **login loops**: callback 302 -> login -> login/start -> callback (repeating)

### Root cause: Login callback loop
The pattern `callback 302 -> login 302 -> login/start 302` means:
1. User completes Zitadel login, redirected to `/admin/callback`
2. Callback succeeds - exchanges code for token, gets userinfo, sets session cookie
3. Redirect to `/admin/setup`
4. `/admin/setup` checks session cookie - **cookie is missing or invalid**
5. Redirects back to `/admin/login`

### Why the cookie might not be set/read:

#### A. Blue-green deploy during OAuth flow (CONFIRMED ISSUE)
- PKCE state is stored in `_pending_auth` dict (in-memory, `auth.py:29`)
- When we deploy, old container is removed and new one starts
- If a user clicked "Login", got redirected to Zitadel, and returns to callback on the NEW container:
  - The PKCE `code_verifier` for their `state` is gone (was in old container's memory)
  - Callback would fail with "Invalid or expired OAuth state"
  - However, we only see 1 such error in 7 days, so this is rare

#### B. Cookie Secure flag mismatch
- `set_session()` sets `secure=True` (via `ADMIN_COOKIE_SECURE` env var)
- If any request goes over HTTP instead of HTTPS, the cookie won't be sent back
- Caddy handles TLS, so this should be fine - but worth verifying

#### C. Browser third-party cookie blocking
- The session cookie is first-party (`mcp.pantalytics.com` -> `mcp.pantalytics.com`)
- Should NOT be blocked, but some privacy extensions might interfere
- Safari's Intelligent Tracking Prevention could theoretically interfere

#### D. OPTIONS/CORS preflight (CONFIRMED ISSUE)
- Logs show `OPTIONS /admin/callback` returning **405 Method Not Allowed**
- This means CORS preflight fails - the browser may block the actual callback request
- This happens when the browser considers the callback a cross-origin request
- Fix: add CORS headers for the callback endpoint, or handle OPTIONS

#### E. Silent OAuth failures (CONFIRMED ISSUE)
- `auth.py:281-295`: Token exchange failure shows error page (good)
- `auth.py:309-317`: Userinfo fetch failure silently redirects to `/admin/login` (bad)
- Users see a loop with no explanation of what went wrong

#### F. No token introspection caching (PERFORMANCE)
- `oauth.py:58-136`: Every MCP request hits Zitadel introspection endpoint
- No caching, no retry logic, no exponential backoff
- Timeout silently returns None (`oauth.py:131-136`)

### Recommended fixes:
1. **Persist PKCE state** in Postgres instead of in-memory dict (survives deploys)
2. **Handle OPTIONS** on `/admin/callback` (return 200 with CORS headers)
3. **Show error page** on userinfo failure instead of silent redirect to login
4. **Add structured logging** to auth flow (login start, callback, session set, session read)
5. **Cache token introspection** results briefly (e.g. 60s) to reduce Zitadel load
6. **Add retry logic** to token introspection with exponential backoff

---

## 2. Zitadel Email Verification

### How Zitadel email verification works:
1. User registers with email + password
2. Zitadel sends a verification email with a 6-digit code
3. User enters the code on the verification page
4. If verified, user can proceed to login

### "Could not verify email" causes:
1. **SMTP not configured** - Zitadel Cloud handles this, so unlikely on our EU instance
2. **Code expired** - Default expiry is 1 hour. If user waits too long, code expires
3. **Code already used** - Each code is single-use
4. **Rate limiting** - Too many verification attempts
5. **Email not delivered** - Spam filters, typo in email

### Zitadel default settings:
- **Verification code expiry**: 1 hour
- **Rate limit**: ~3 failed attempts then blocked, user must request new code
- **SMTP sender**: `notification@zitadel.cloud` (Zitadel Cloud built-in)
- **Session lifetime**: 12 hours (Login UI V2)
- **Access token lifetime**: 12 hours (configurable per OIDC app)
- **Refresh token lifetime**: 7 days idle / 30 days absolute
- **Clock skew tolerance**: 5 seconds (irrelevant for us since we use introspection, not local JWT)

### What to check:
- Zitadel Console > Settings > SMTP - custom SMTP possible to improve deliverability
- Zitadel Console > Projects > App > Token Settings - verify token lifetimes
- Some corporate email filters block `notification@zitadel.cloud` - custom SMTP fixes this

### Our specific situation:
- We use Zitadel Cloud EU instance (`odoo-mcp-pro-xywtof.eu1.zitadel.cloud`)
- SMTP is managed by Zitadel - `notification@zitadel.cloud` may land in spam
- Users with corporate email (e.g. company domains) more likely to hit spam filters
- **Action**: Consider setting up custom SMTP in Zitadel (e.g. via Brevo) for reliable delivery
- **Action**: Advise users to check spam folder for verification email

---

## 3. Claude MCP Connection Stability

### When does Claude disconnect from an MCP server?

#### Token expiry
- Zitadel default access token lifetime: **12 hours**
- Zitadel default refresh token lifetime: **30 days** (if offline_access scope)
- Claude should auto-refresh using the refresh token
- If refresh token is not issued or expires, user must reconnect

#### Server restart / deploy
- Our blue-green deploy keeps one container running at all times
- But Caddy's health checks take 5-10 seconds to detect the new upstream
- During this window, requests may fail with 503 "no upstreams available"
- Claude may interpret this as "server is down" and disconnect

#### Idle timeout
- Our Streamable HTTP transport uses SSE for server->client messages
- Caddy may close idle connections (default: no timeout for proxied connections)
- Claude.ai may close idle MCP connections on their side

#### Session ID mismatch
- MCP sessions are in-memory (`StreamableHTTP session manager`)
- When we deploy, old sessions are lost
- Claude sends `Mcp-Session-Id` header - if the server doesn't recognize it, it creates a new transport
- This is logged: "Created new transport with session ID: ..."
- This is EXPECTED behavior after deploy - it should work transparently

### Token timeline for our setup:
- **Access token**: 12 hours (Zitadel default) - after this, Claude must refresh
- **Refresh token**: 7 days idle / 30 days absolute - after this, user must reconnect
- **Session cookie (admin panel)**: 8 hours (our setting in auth.py:25)
- **Registry cache**: 30 minutes (registry.py:25) - Odoo connection re-created after this

### Why Claude keeps disconnecting:
1. **503 during deploy** - even brief, Claude may mark the server as failed
2. **Token expiry without refresh** - if we don't issue refresh tokens or `offline_access` scope is missing
3. **SSE connection dropped** by Caddy during deploy
4. **Claude-side idle timeout** - claude.ai may drop inactive MCP connections
5. **Refresh token expired** - after 7 days of no use, user must fully re-authenticate

### Critical finding: Claude does NOT reliably auto-refresh tokens
This is a known bug across ALL Claude clients:
- **Claude Code**: `/mcp reconnect` does not refresh expired tokens ([#19481](https://github.com/anthropics/claude-code/issues/19481)). OAuth tokens not persisted between sessions ([#40582](https://github.com/anthropics/claude-code/issues/40582)).
- **Claude Desktop**: Broken OAuth token exchange after updates ([claude-ai-mcp #5](https://github.com/anthropics/claude-ai-mcp/issues/5)).
- **Claude.ai**: Connections are per-conversation. New chat = new MCP session.
- **Not Claude-specific**: Gemini CLI has the same issue ([#23776](https://github.com/google-gemini/gemini-cli/issues/23776)).

### MCP session behavior:
- Each `Mcp-Session-Id` is in-memory on our server
- Blue-green deploy = old sessions gone, server returns 404
- Per MCP spec, client MUST re-initialize on 404 (this works)
- But re-initialize != re-authenticate. If the token is still valid, it reconnects transparently
- If the token expired, user must manually reconnect

### Recommended fixes:
1. **Increase access token lifetime in Zitadel** from 12h to 24-48h (reduces reconnect frequency since Claude can't auto-refresh)
2. **Ensure refresh tokens are issued** - check Zitadel OIDC app for `offline_access` scope
3. **Keep old container running 30s** after new is healthy (drain in-flight requests)
4. **Cache token introspection** results for 60s (reduces Zitadel load and latency)
5. **Accept that reconnects will happen** - focus on making reconnect fast and painless

---

## 4. Blue-Green Deploy Issues

### Current deploy flow:
```
1. Build new image
2. Start new container
3. Wait for healthy (up to 30s)
4. Remove old container (docker compose rm -f -s)
5. Sleep 5s
6. Run smoke tests
```

### Problems:
1. **PKCE state lost** - in-memory `_pending_auth` dict is per-process
2. **MCP sessions lost** - in-memory session manager
3. **Connection registry lost** - cached Odoo connections must be re-created
4. **Brief 503 window** - between old container removal and Caddy health check update

### Recommended deploy improvements:
1. Move PKCE state to Postgres (eliminates login failures during deploy)
2. Extend overlap: keep old container running 30s after new is healthy
3. Caddy: reduce health check interval from 5s to 2s
4. Add `X-No-Deploy` header or maintenance mode for graceful draining

---

## 5. Action Items (Priority Order)

### P0 - Fix now (biggest user impact)
- [ ] **Increase Zitadel access token lifetime** from 12h to 48h (Zitadel Console > Projects > App > Token Settings). This is the #1 fix because Claude cannot auto-refresh tokens.
- [ ] **Move PKCE state from in-memory to Postgres** (fixes login during deploy). `auth.py:29` `_pending_auth` dict must survive container restarts.
- [ ] **Show error page** on OAuth failure instead of silent redirect loop (`auth.py:309-317`)

### P1 - Fix this week
- [ ] **Handle OPTIONS** on `/admin/callback` (return 200 with CORS headers, fixes 405 for 2 users)
- [ ] **Keep old container running 30s** after new container is healthy (drain in-flight requests in `deploy.sh`)
- [ ] **Verify `offline_access` scope** is requested and refresh tokens are issued (check Zitadel OIDC app config)
- [ ] **Cache token introspection** results for 60s in `oauth.py` (reduces Zitadel round-trips)

### P2 - Improve reliability
- [ ] **Add structured logging** for auth flow (login start, callback success/fail, session set, session read)
- [ ] **Set up custom SMTP** in Zitadel via Brevo (fixes email deliverability for corporate domains)
- [ ] **Add retry logic** to token introspection with exponential backoff (`oauth.py:131-136`)

### P3 - Monitor
- [ ] Track login success rate in PostHog (currently ~95%: 62/65 callbacks succeed)
- [ ] Monitor Claude MCP reconnection patterns
- [ ] Watch for Zitadel Cloud email delivery issues

### Won't fix (client-side bugs)
- Claude Code OAuth tokens not persisted between sessions ([#40582](https://github.com/anthropics/claude-code/issues/40582))
- Claude Code `/mcp reconnect` doesn't refresh tokens ([#19481](https://github.com/anthropics/claude-code/issues/19481))
- Claude Desktop OAuth breaks after updates ([claude-ai-mcp #5](https://github.com/anthropics/claude-ai-mcp/issues/5))
- These are Anthropic bugs. Our best mitigation is longer-lived access tokens.

---

## 6. Monitoring & Health System

### Goal
Know the system is healthy without users telling us. Three levels:
- **Green**: everything working, no action needed
- **Orange**: degraded, investigate within hours
- **Red**: broken, fix immediately

### 6.1 PostHog Events (implemented)

Server-side events, privacy-respecting (zitadel_sub as distinct_id, no PII in properties):

| Event | Meaning | Healthy signal |
|-------|---------|----------------|
| `mcp_tool_called` | User made an MCP tool call | Steady daily volume |
| `auth_login_success` | User logged into admin panel | Should match callback count |
| `auth_callback_error` | Zitadel returned OAuth error | Should be 0 |
| `auth_state_invalid` | PKCE state lost (deploy during login) | Should be 0 |
| `auth_token_exchange_failed` | Code-to-token exchange failed | Should be 0 |
| `auth_userinfo_failed` | Zitadel userinfo endpoint failed | Should be 0 |

### 6.2 PostHog Alerts to Set Up

Create these alerts in PostHog (Alerts > New):

| Alert | Condition | Level |
|-------|-----------|-------|
| "Auth failures" | Any `auth_*_failed` or `auth_*_error` > 0 in 1 hour | Red |
| "No tool calls" | `mcp_tool_called` count = 0 for 6 hours (during business hours) | Orange |
| "State lost during deploy" | `auth_state_invalid` > 0 in 1 hour | Orange |
| "Usage drop" | `mcp_tool_called` DAU drops > 50% week-over-week | Orange |

### 6.3 Infrastructure Health (existing)

Already monitored via deploy.sh smoke tests:

| Check | Endpoint | Expected | Frequency |
|-------|----------|----------|-----------|
| MCP server up | `/.well-known/oauth-protected-resource` | 200 | Every deploy + Caddy health every 5s |
| OAuth discovery | `/.well-known/oauth-authorization-server` | 200 | Every deploy |
| DCR works | `POST /register` | 200 | Every deploy |
| Zitadel proxy | `/authorize` | 301/302 | Every deploy |

### 6.4 Missing Monitoring (to add)

| What | How | Priority |
|------|-----|----------|
| **Uptime monitoring** | External service (e.g. BetterUptime, UptimeRobot) pinging `/.well-known/oauth-protected-resource` every 60s. Alert if down > 2 min. | P0 |
| **Zitadel health** | Ping `https://odoo-mcp-pro-xywtof.eu1.zitadel.cloud/.well-known/openid-configuration` every 5 min | P1 |
| **Postgres health** | Docker healthcheck already runs `pg_isready`. Add PostHog event on connection pool exhaustion. | P2 |
| **Deploy success tracking** | Log deploy events to PostHog: `deploy_started`, `deploy_completed`, `deploy_failed` | P1 |
| **SSL certificate expiry** | Caddy auto-renews, but monitor cert expiry as backup | P2 |

### 6.5 Dashboard: "Is the system healthy?"

Build a PostHog dashboard called "MCP System Health" with these panels:

1. **Tool calls per day** (trend, last 14 days) - should be growing or stable
2. **Unique active users per day** (trend, DAU) - our key metric
3. **Auth failures** (trend, all auth_*_failed events) - should be flat zero
4. **Login success rate** (formula: auth_login_success / (auth_login_success + all failures)) - should be > 95%
5. **Tool call errors** (mcp_tool_called where error=true) - should be < 5% of total
6. **New registrations per day** (from Postgres, or add PostHog event)

### 6.6 Future: Public Status Page

When we have enough users, consider a public status page at `status.pantalytics.com`:
- Shows current status of MCP server, Zitadel, Odoo connectivity
- Historical uptime percentage
- Incident history
- Can be built with BetterUptime, Instatus, or custom with PostHog data

---

## 7. Stability Roadmap

### Week 1 (now)
- [ ] Increase Zitadel token lifetime to 48h
- [ ] Set up external uptime monitoring (BetterUptime free tier)
- [ ] Create PostHog "MCP System Health" dashboard
- [ ] Set up PostHog alerts for auth failures

### Week 2
- [ ] Move PKCE state to Postgres
- [ ] Add deploy events to PostHog
- [ ] Keep old container running 30s after deploy
- [ ] Set up custom SMTP in Zitadel via Brevo

### Week 3
- [ ] Cache token introspection (60s)
- [ ] Add retry logic to introspection
- [ ] Error pages instead of silent redirect loops
- [ ] Handle OPTIONS on callback

### Ongoing
- [ ] Review PostHog dashboard weekly
- [ ] Respond to alerts within 4 hours
- [ ] Document incidents and root causes
