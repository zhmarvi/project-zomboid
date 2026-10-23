#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
for tool in python3 shellcheck yamllint helm; do
  command -v "$tool" >/dev/null || { printf 'Required validation tool missing: %s\n' "$tool" >&2; exit 1; }
done
for script in scripts/*.sh tests/*.sh; do bash -n "$script"; done
shellcheck scripts/*.sh tests/*.sh
yamllint .github compose.yaml examples charts/project-zomboid/Chart.yaml charts/project-zomboid/values.yaml
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_config.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_security_patches.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_lifecycle.py' -v
bash tests/test_security_updates.sh
helm lint charts/project-zomboid --strict --set server.existingSecret.name=validation
python3 tests/test_chart.py
printf 'All script, unit, and Helm checks passed.\n'
