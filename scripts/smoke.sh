#!/usr/bin/env bash
# Usage: smoke.sh [EXPECTED_VERSION]
# Hits the Service through a port-forward. If EXPECTED_VERSION is given, the
# version reported by / has to match it.
set -euo pipefail

svc=${SERVICE:-greeter}
ns=${NAMESPACE:-demo}
port=${SMOKE_PORT:-18480}
want=${1:-}

fail() { echo "smoke FAIL: $*" >&2; exit 1; }

log=$(mktemp)
kubectl -n "$ns" port-forward "svc/$svc" "$port:80" >"$log" 2>&1 &
pf=$!
# wait only to keep bash from printing "Terminated"; its status (143) must not
# leak out, or a passing smoke test would exit non-zero
trap 'kill "$pf" 2>/dev/null; wait "$pf" 2>/dev/null || true; rm -f "$log"' EXIT

# Wait for the forward by its own output. Just curling the port could end up
# talking to whatever else already listens there.
for _ in $(seq 20); do
  grep -q "Forwarding from" "$log" && break
  kill -0 "$pf" 2>/dev/null || fail "port-forward exited: $(cat "$log")"
  sleep 0.5
done
grep -q "Forwarding from" "$log" || fail "port-forward did not come up"

base=http://127.0.0.1:$port
get() { curl -fsS --max-time 5 "$base$1"; }

# Plain variables instead of "curl | grep -q": with pipefail, grep closing
# the pipe early can fail the pipeline even though the match was found.
health=$(get /health) || fail "GET /health"
[[ $health == *'"status":"ok"'* ]] || fail "/health returned: $health"

body=$(get /) || fail "GET /"
got=$(jq -r .version <<<"$body")
if [[ -n $want && $got != "$want" ]]; then
  fail "version is $got, expected $want"
fi

metrics=$(get /metrics) || fail "GET /metrics"
[[ $metrics == *http_requests_total* ]] || fail "/metrics has no http_requests_total"

echo "smoke ok, version $got"
