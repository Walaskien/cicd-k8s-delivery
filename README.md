# cicd-k8s-delivery

[![ci](https://github.com/Walaskien/cicd-k8s-delivery/actions/workflows/ci.yml/badge.svg)](https://github.com/Walaskien/cicd-k8s-delivery/actions/workflows/ci.yml)

A small Flask service and a GitHub Actions pipeline that ships it. I built it to see a bad release get caught and rolled back by the pipeline itself, and to be able to trigger that on demand instead of waiting for a real bad deploy.

The pipeline runs lint and tests, builds the image once, deploys it with Helm into a throwaway kind cluster, runs a smoke test, and rolls back if the release is bad. It only ever deploys to kind inside the CI runner. The image is passed between jobs as a tarball, and the same tarball is pushed to GHCR from `main` after the deploy and the four rollback cases pass. Nothing is pushed from pull requests.

Two things can catch a bad release. Helm does it through the readiness probe and `--rollback-on-failure` when pods never become ready. `scripts/smoke.sh` does it when the release is ready but wrong, and then `scripts/deploy.sh` runs `helm rollback` to the last superseded revision.

## Run it

You need docker, kind, helm 4, kubectl, jq and python3.

```
make venv
make lint
make test
make kind-up        # cluster "cicd-demo", kubeconfig goes to ./.kubeconfig
make deploy         # build, load into kind, helm upgrade --install, smoke test
make rollback-demo FAULT=broken-endpoint
make kind-down
```

The Makefile points `KUBECONFIG` at the repo's own `.kubeconfig`, so your current kubectl context is not touched. On GitHub you can also run the `rollback-demo` workflow and pick a fault.

## Rollback demo

`scripts/rollback-demo.sh` installs a healthy release, upgrades it with a fault switched on through `config.fault` in the chart values, and checks that the release ends up `deployed`, the fault is gone from the values and the smoke test passes again. The faults are `crash-on-start` and `unhealthy`, which Helm catches itself, `broken-endpoint` (`/health` is fine, `/` returns 500), which only the smoke test catches, and `none` as a control run where the upgrade stays.

After a caught fault the history looks like this. Revision 3 is the rollback, a new revision that restores the values of revision 1:

```
REVISION  STATUS      DESCRIPTION
1         superseded  Install complete
2         failed      Upgrade "greeter" failed: resource Deployment/demo/greeter not ready ...
3         deployed    Rollback to 1
```

A typo in `config.fault` is refused by `chart/greeter/values.schema.json` before anything is deployed.

## What was hard

Timing. The timeouts (90s for a deploy, 45s for the bad upgrade in the demo) were picked for an idle machine. While other containers were busy on the same Colima VM, a rollout that normally passes hit the timeout. The `broken-endpoint` case was affected too: with a 60s limit on the loaded VM the new pod was not ready in time, so Helm rolled back first and the smoke test never ran. With `BAD_TIMEOUT=120s` the smoke test caught it again. The end state was the same every time. On a busy host raise `HELM_TIMEOUT` and `BAD_TIMEOUT`.

## What I checked and what I did not

On GitHub Actions (ubuntu-24.04, Helm v4.2.4, kind v0.33.0):

- `ci` on `main` is green on all jobs, about 2m15s end to end on the first runs.
- `rollback-demo` ran once per fault, all four green, and the history ended with `Rollback to 1` each time except `none`.
- GHCR push works with only `GITHUB_TOKEN`. Both tags answered an anonymous manifest request. I did not pull and run the image from there.
- The `rollback` job in `ci` was checked on two throwaway branches. With `smoke.sh` cut short so it no longer checks `/`, `ci` was green without the job and red with it (`the broken release was NOT caught`).

Locally on a Mac under Colima:

- `pytest`, 17 passed on Python 3.9. 8 of them test the exit codes of `deploy.sh` and `rollback-demo.sh` against stub `helm`, `kubectl` and `smoke.sh`, not a cluster.
- `ruff`, `yamllint`, `hadolint`, `shellcheck`, `helm lint --strict`, `kubeconform -strict` and `actionlint` are clean.
- `make deploy`, `make smoke` and all four faults against a real kind cluster gave the same outcomes as on GitHub.

Not checked: the `pull_request` path has not run yet (only pushes and manual dispatches), and neither has the `cancel-in-progress` rule for PRs.

Not done:

- kind in CI is created fresh every run, so the regular deploy job only sees revision 1. A failed smoke test there falls back to `helm uninstall`. The rollback path is exercised by the `rollback` job, which installs a good revision first.
- The fault is a switch in the app, not a real regression.
- The smoke test is three HTTP checks through a port-forward to one pod. No ingress, no load.
- Helm is pinned to v4. `--rollback-on-failure` is what Helm 3 called `--atomic`, so Helm 3 would need that one flag changed.
- No PodDisruptionBudget or HPA, and the resource requests and limits are guesses, not measured.
- The base image is pinned by tag, not digest. No image scanning or signing.
