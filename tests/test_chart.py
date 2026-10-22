"""Render supported chart modes and reject invalid combinations (no cluster needed)."""
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = str(ROOT / "charts/project-zomboid")


def render(*settings, succeeds=True):
    command = ["helm", "template", "test", CHART, "--namespace", "zomboid"]
    for setting in settings:
        command.extend(["--set", setting])
    result = subprocess.run(command, capture_output=True, text=True)
    assert (result.returncode == 0) == succeeds, result.stderr
    return result.stdout


base = "server.existingSecret.name=test-admin"
default = render(base)
assert "replicas: 1" in default and "volumeClaimTemplates:" in default
assert 'kubernetes.io/arch: amd64' in default and 'readOnlyRootFilesystem: true' in default
assert 'automountServiceAccountToken: false' in default
assert "protocol: TCP" not in default
assert 'mountPath: /home/steam' in default and 'runAsUser: 10000' in default
assert '"-adminpassword"' not in default
existing = render(base, "persistence.server.existingClaim=server", "persistence.data.existingClaim=data")
assert 'volumeClaimTemplates:' not in existing
assert 'claimName: server' in existing and 'claimName: data' in existing
render(base, "service.type=ClusterIP")
render(base, "service.type=NodePort")
render(base, "hostNetwork=true", "service.type=ClusterIP")
digest = render(base, "image.digest=sha256:" + "a" * 64)
assert '@sha256:' in digest
render(succeeds=False)
render(base, "service.gamePort=16262", succeeds=False)
render(base, "terminationGracePeriodSeconds=150", succeeds=False)
render(base, "hostNetwork=true", succeeds=False)
render(base, "server.settings.UNKNOWN=foo", succeeds=False)
render(base, "service.gamePort=70000", succeeds=False)
render(base, "server.name=../escape", succeeds=False)
print("Helm configuration matrix passed")
