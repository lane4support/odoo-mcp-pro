#!/usr/bin/env bash
# Zero-downtime blue-green deploy for odoo-mcp-pro.
# Usage: ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.multi-tenant.yml"
DOMAIN="${DOMAIN:-mcp.pantalytics.com}"

# Determine which slot is currently running
if docker inspect mcp-blue --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
    OLD=mcp-blue
    NEW=mcp-green
else
    OLD=mcp-green
    NEW=mcp-blue
fi

echo "==> Current: $OLD, deploying: $NEW"

# Pull latest code
echo "==> Pulling latest code..."
cd .. && git pull && cd deploy

# Build the new image
echo "==> Building image..."
$COMPOSE build --no-cache $NEW

# Start the new container
echo "==> Starting $NEW..."
$COMPOSE up -d $NEW

# Wait for healthy
echo "==> Waiting for $NEW to be healthy..."
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format '{{.State.Health.Status}}' $NEW 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        echo "==> $NEW is healthy!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "==> ERROR: $NEW did not become healthy in 30s, rolling back"
        $COMPOSE stop $NEW
        exit 1
    fi
    sleep 1
done

# Drain: keep old container running 30s to finish in-flight requests
echo "==> Draining $OLD for 30s..."
sleep 30

# Remove the old container
echo "==> Removing $OLD..."
$COMPOSE rm -f -s $OLD

# Wait for Caddy DNS
sleep 5

# Smoke tests
echo "==> Running smoke tests on $DOMAIN..."
FAILED=0
for ENDPOINT in \
    "/.well-known/oauth-protected-resource" \
    "/.well-known/oauth-authorization-server" \
; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN$ENDPOINT" 2>/dev/null || echo "000")
    if [ "$CODE" != "200" ]; then
        echo "    FAIL: $ENDPOINT returned $CODE"
        FAILED=1
    else
        echo "    OK: $ENDPOINT"
    fi
done

CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN/authorize?response_type=code&client_id=test" 2>/dev/null || echo "000")
if [ "$CODE" = "404" ] || [ "$CODE" = "502" ] || [ "$CODE" = "000" ]; then
    echo "    FAIL: /authorize returned $CODE (Zitadel proxy broken)"
    FAILED=1
else
    echo "    OK: /authorize (returned $CODE)"
fi

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "https://$DOMAIN/register" \
    -H "Content-Type: application/json" \
    -d '{"redirect_uris":["https://test.example.com/cb"],"client_name":"smoke-test"}' 2>/dev/null || echo "000")
if [ "$CODE" != "200" ]; then
    echo "    FAIL: /register returned $CODE"
    FAILED=1
else
    echo "    OK: /register"
fi

if [ "$FAILED" -eq 1 ]; then
    echo "==> WARNING: Some smoke tests failed! Check Caddy logs."
else
    echo "==> All smoke tests passed"
fi

echo "==> Deploy complete: $NEW is live"
