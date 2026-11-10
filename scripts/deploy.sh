#!/usr/bin/env bash
# Usage: deploy.sh IMAGE_REPO TAG [extra helm args]
#
# Exit codes:
#   0  deployed and the smoke test passed
#   2  helm gave up and rolled the release back itself
#   3  helm was fine with it, the smoke test was not, we rolled back
set -euo pipefail

repo=${1:?image repository}
tag=${2:?image tag}
shift 2

release=${RELEASE:-greeter}
ns=${NAMESPACE:-demo}
timeout=${HELM_TIMEOUT:-90s}
root=$(cd "$(dirname "$0")/.." && pwd)

# --rollback-on-failure is what Helm 3 called --atomic
if ! helm upgrade --install "$release" "$root/chart/greeter" \
    --namespace "$ns" --create-namespace \
    --set image.repository="$repo" --set image.tag="$tag" \
    --rollback-on-failure --timeout "$timeout" "$@"; then
  echo "helm upgrade failed, release rolled back" >&2
  exit 2
fi

if "$root/scripts/smoke.sh" "$tag"; then
  exit 0
fi

# Probes were green but the service misbehaves, so helm does not know.
echo "smoke test failed, rolling back" >&2
prev=$(helm history "$release" -n "$ns" -o json |
  jq -r '[.[] | select(.status == "superseded")] | last | .revision // empty')
if [[ -n $prev ]]; then
  helm rollback "$release" "$prev" -n "$ns" --wait --timeout "$timeout"
else
  echo "no earlier revision, removing the release" >&2
  helm uninstall "$release" -n "$ns"
fi
exit 3
