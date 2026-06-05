#!/usr/bin/env bash
# Smoke test — polls /ping until the target service answers, then asserts
# the response body. Returns 0 on success, non-zero (with a clear message)
# on failure.
#
# Usage:
#   scripts/smoke.sh [BASE_URL] [TIMEOUT_SECONDS]
#
# Examples:
#   scripts/smoke.sh                              # http://localhost:8000, 60s
#   scripts/smoke.sh http://api.staging.acme.io  # 60s default
#   scripts/smoke.sh http://localhost:8000 30    # 30s timeout
#
# Designed to be the same script run locally, in CI, and post-deploy. No
# Python deps, just curl + jq.

set -euo pipefail

BASE_URL="${1:-${SMOKE_BASE_URL:-http://localhost:8000}}"
TIMEOUT="${2:-${SMOKE_TIMEOUT:-60}}"
INTERVAL="${SMOKE_INTERVAL:-1}"
EXPECTED='{"ping":"pong"}'

PING_URL="${BASE_URL%/}/ping"
LIVE_URL="${BASE_URL%/}/api/v1/health/live"

log()  { printf '[smoke] %s\n' "$*" >&2; }
fail() { printf '[smoke] FAIL: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || fail "curl is required"
command -v jq   >/dev/null || fail "jq is required"

log "target=$BASE_URL timeout=${TIMEOUT}s interval=${INTERVAL}s"

# ---------------------------------------------------------------------------
# 1. Wait for /ping to become reachable.
# ---------------------------------------------------------------------------
deadline=$(( $(date +%s) + TIMEOUT ))
attempt=0
while :; do
    attempt=$(( attempt + 1 ))
    if response=$(curl --silent --show-error --max-time 5 --fail-with-body "$PING_URL" 2>&1); then
        log "ping reachable after ${attempt} attempt(s)"
        break
    fi
    if [[ $(date +%s) -ge $deadline ]]; then
        fail "service did not respond at $PING_URL within ${TIMEOUT}s (last: ${response:-no response})"
    fi
    sleep "$INTERVAL"
done

# ---------------------------------------------------------------------------
# 2. Assert payload shape.
# ---------------------------------------------------------------------------
canonical=$(echo "$response" | jq -c -S '.')
if [[ "$canonical" != "$EXPECTED" ]]; then
    fail "/ping returned $canonical, expected $EXPECTED"
fi
log "OK  $PING_URL -> $canonical"

# ---------------------------------------------------------------------------
# 3. Assert liveness probe is also green.
# ---------------------------------------------------------------------------
if ! live=$(curl --silent --show-error --max-time 5 --fail-with-body "$LIVE_URL" 2>&1); then
    fail "/health/live unreachable: $live"
fi
if [[ "$(echo "$live" | jq -r '.status')" != "ok" ]]; then
    fail "/health/live status != ok: $live"
fi
log "OK  $LIVE_URL -> $(echo "$live" | jq -c '{status,service,version}')"

# ---------------------------------------------------------------------------
# 4. Assert the request-id header round-trips.
# ---------------------------------------------------------------------------
correlation="smoke-$(date +%s%N)"
header=$(curl --silent --output /dev/null --max-time 5 \
    -H "X-Request-ID: $correlation" \
    -w '%header{x-request-id}' "$PING_URL")
if [[ "$header" != "$correlation" ]]; then
    fail "X-Request-ID not preserved: sent=$correlation got=$header"
fi
log "OK  X-Request-ID round-trip"

log "all smoke checks passed."
