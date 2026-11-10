#!/usr/bin/env bash
# Usage: rollback-demo.sh IMAGE_REPO TAG FAULT
# FAULT is crash-on-start, unhealthy, broken-endpoint, or none (control run).
#
# Installs a good release, upgrades it with the fault switched on, and checks
# that the cluster ends up on a healthy release again.
set -euo pipefail

repo=${1:?image repository}
tag=${2:?image tag}
fault=${3:?fault}

case $fault in
  crash-on-start | unhealthy | broken-endpoint | none) ;;
  *) echo "unknown fault: $fault" >&2; exit 1 ;;
esac

release=${RELEASE:-greeter}
ns=${NAMESPACE:-demo}
root=$(cd "$(dirname "$0")/.." && pwd)

echo "### revision 1: healthy release"
"$root/scripts/deploy.sh" "$repo" "$tag"

echo
echo "### upgrade with fault: $fault"
# The control run changes the greeting instead, so the upgrade is not a no-op
# and still has to restart the pods through the config checksum.
if [[ $fault == none ]]; then
  change=(--set "config.greeting=hello again")
else
  change=(--set "config.fault=$fault")
fi
# shorter timeout here, the broken pods are not going to recover
rc=0
HELM_TIMEOUT=${BAD_TIMEOUT:-45s} "$root/scripts/deploy.sh" "$repo" "$tag" "${change[@]}" || rc=$?

echo
echo "### release history"
helm history "$release" -n "$ns"
kubectl -n "$ns" get pods

if [[ $fault == none ]]; then
  [[ $rc -eq 0 ]] || { echo "control upgrade failed (rc=$rc)" >&2; exit 1; }
  echo "control run: healthy upgrade was kept"
  exit 0
fi

case $rc in
  0) echo "the broken release was NOT caught" >&2; exit 1 ;;
  2) echo "caught by helm (probes), rolled back" ;;
  3) echo "caught by the smoke test, rolled back" ;;
  *) echo "unexpected exit code $rc" >&2; exit 1 ;;
esac

# Whatever caught it, the cluster has to be serving the good release now.
status=$(helm status "$release" -n "$ns" -o json | jq -r .info.status)
[[ $status == deployed ]] || { echo "release status is $status" >&2; exit 1; }

fault_left=$(helm get values "$release" -n "$ns" -o json | jq -r '.config.fault // ""')
[[ -z $fault_left ]] || { echo "fault still set: $fault_left" >&2; exit 1; }

kubectl -n "$ns" rollout status "deploy/$release" --timeout=60s
"$root/scripts/smoke.sh" "$tag"
echo "rollback verified"
