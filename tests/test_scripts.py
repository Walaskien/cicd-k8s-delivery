"""Exit codes and rollback checks of the deploy scripts, run against stubs.

helm, kubectl and smoke.sh are fakes, so this says nothing about a real
cluster. It only pins down what the scripts decide from what helm tells them.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

NTH = """
nth() {  # nth N WORD... : the Nth word, or the last one when N is past the end
  local n=$1; shift
  local words=("$@")
  if (( n > ${#words[@]} )); then n=${#words[@]}; fi
  echo "${words[n-1]}"
}
"""

HELM = (
    "#!/usr/bin/env bash\n"
    + NTH
    + """
echo "helm $*" >> "$STUB_DIR/argv.log"
case $1 in
  upgrade)
    n=$(grep -c '^helm upgrade' "$STUB_DIR/argv.log")
    rc=$(nth "$n" ${UPGRADE_RCS:-0})
    [[ $rc -eq 0 ]] || echo "Error: upgrade failed" >&2
    exit "$rc" ;;
  history)
    if [[ " $* " == *" -o json "* ]]; then
      cat "$STUB_DIR/history.json"
    else
      echo "REVISION STATUS"
    fi ;;
  status) echo '{"info": {"status": "deployed"}}' ;;
  get) echo '{"config": {}}' ;;
esac
"""
)

SMOKE = (
    "#!/usr/bin/env bash\n"
    + NTH
    + """
echo "smoke $*" >> "$STUB_DIR/argv.log"
n=$(grep -c '^smoke' "$STUB_DIR/argv.log")
exit "$(nth "$n" ${SMOKE_RCS:-0})"
"""
)

KUBECTL = '#!/usr/bin/env bash\necho "kubectl $*" >> "$STUB_DIR/argv.log"\n'


def rev(n, status, description=""):
    return {"revision": n, "status": status, "description": description}


@pytest.fixture
def env(tmp_path):
    scripts = tmp_path / "scripts"
    bin_dir = tmp_path / "bin"
    scripts.mkdir()
    bin_dir.mkdir()
    for name in ("deploy.sh", "rollback-demo.sh"):
        shutil.copy(SCRIPTS / name, scripts / name)
    for path, body in (
        (scripts / "smoke.sh", SMOKE),
        (bin_dir / "helm", HELM),
        (bin_dir / "kubectl", KUBECTL),
    ):
        path.write_text(body)
    for path in list(scripts.iterdir()) + list(bin_dir.iterdir()):
        path.chmod(0o755)
    (tmp_path / "argv.log").touch()
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_DIR": str(tmp_path),
        "HOME": str(tmp_path),
    }


def run(env, script, *args, history=None, **extra):
    stub = Path(env["STUB_DIR"])
    (stub / "history.json").write_text(json.dumps(history or []))
    result = subprocess.run(
        ["bash", str(stub / "scripts" / script), *args],
        env={**env, **extra},
        capture_output=True,
        text=True,
        timeout=30,
    )
    log = (stub / "argv.log").read_text()
    return result, log


def test_deploy_upgrade_fails_exit_2(env):
    result, _ = run(env, "deploy.sh", "repo", "t1", UPGRADE_RCS="1")
    assert result.returncode == 2


def test_deploy_smoke_fails_rolls_back_to_last_superseded(env):
    history = [
        rev(1, "superseded"),
        rev(2, "failed"),
        rev(3, "superseded"),
        rev(4, "deployed"),
    ]
    result, log = run(env, "deploy.sh", "repo", "t1", history=history, SMOKE_RCS="1")
    assert result.returncode == 3
    assert "helm rollback greeter 3 " in log
    assert "helm uninstall " not in log


def test_deploy_smoke_fails_first_release_is_uninstalled(env):
    result, log = run(
        env, "deploy.sh", "repo", "t1", history=[rev(1, "deployed")], SMOKE_RCS="1"
    )
    assert result.returncode == 3
    assert "helm uninstall greeter " in log
    assert "helm rollback " not in log


def test_deploy_ok_exit_0(env):
    result, log = run(env, "deploy.sh", "repo", "t1", history=[rev(1, "deployed")])
    assert result.returncode == 0
    assert "helm rollback " not in log and "helm uninstall " not in log


def test_demo_failed_upgrade_without_bad_revision_is_not_verified(env):
    # helm upgrade fails (bad flag, API down), revision 1 stays deployed:
    # nothing was rolled back, so the demo must not claim it was.
    result, _ = run(
        env,
        "rollback-demo.sh",
        "repo",
        "t1",
        "broken-endpoint",
        history=[rev(1, "deployed")],
        UPGRADE_RCS="0 1",
    )
    assert result.returncode == 1
    assert "rollback verified" not in result.stdout


@pytest.mark.parametrize(
    "extra",
    [
        {"UPGRADE_RCS": "0 1"},  # helm rolled back by itself
        {"SMOKE_RCS": "0 1 0"},  # smoke test caught it, deploy.sh rolled back
    ],
)
def test_demo_verified_when_history_has_the_rollback(env, extra):
    history = [
        rev(1, "superseded", "Install complete"),
        rev(2, "failed" if "UPGRADE_RCS" in extra else "superseded", "Upgrade"),
        rev(3, "deployed", "Rollback to 1"),
    ]
    result, _ = run(
        env, "rollback-demo.sh", "repo", "t1", "unhealthy", history=history, **extra
    )
    assert result.returncode == 0, result.stderr
    assert "rollback verified" in result.stdout


def test_demo_unknown_fault_exits_before_helm(env):
    result, log = run(env, "rollback-demo.sh", "repo", "t1", "bogus")
    assert result.returncode == 1
    assert log == ""
