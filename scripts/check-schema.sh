#!/usr/bin/env bash
# The chart schema has to refuse a bad value before anything is deployed.
set -euo pipefail

cd "$(dirname "$0")/.."
chart=chart/greeter

for fault in "" crash-on-start unhealthy broken-endpoint; do
  helm template greeter "$chart" --set "config.fault=$fault" >/dev/null
done

for bad in config.fault=unhealty replicaCount=0 service.port=70000 image.pullPolicy=Sometimes; do
  if helm template greeter "$chart" --set "$bad" >/dev/null 2>&1; then
    echo "schema accepted $bad"
    exit 1
  fi
done
echo "chart schema ok"
