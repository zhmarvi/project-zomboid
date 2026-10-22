#!/usr/bin/env bash
set -Eeuo pipefail

# Run during image builds only. Never patch a running game container.
export DEBIAN_FRONTEND=noninteractive
manifest=${1:-/usr/local/share/project-zomboid/apt-packages.txt}
apt-get update
# Include dependency additions required for vendor fixes, without removing packages.
apt-get -y --no-install-recommends upgrade --with-new-pkgs

# Optional explicit upgrades for a reviewed advisory (package or package=version).
# Refuse new packages and downgrades; missing vendor fixes must fail visibly.
targets=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line=${line%%#*}
  read -r -a fields <<< "$line"
  [[ ${#fields[@]} -eq 0 ]] && continue
  [[ ${#fields[@]} -eq 1 && ${fields[0]} =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?(=[a-zA-Z0-9.+:~_-]+)?$ ]] || {
    printf 'Invalid APT target: %s\n' "$line" >&2; exit 1;
  }
  package=${fields[0]%%=*}
  [[ $(dpkg-query -W -f='${Status}' "$package") == 'install ok installed' ]] || {
    printf 'APT target is not installed: %s\n' "$package" >&2; exit 1;
  }
  targets+=("${fields[0]}")
done < "$manifest"
if (( ${#targets[@]} )); then
  apt-get install -y --no-install-recommends --only-upgrade "${targets[@]}"
fi
mkdir -p /usr/local/share/project-zomboid
dpkg-query -W -f='${binary:Package}\t${Version}\n' \
  > /usr/local/share/project-zomboid/apt-inventory.tsv
apt-get clean
rm -rf /var/lib/apt/lists/*
