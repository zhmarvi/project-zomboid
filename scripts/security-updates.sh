#!/usr/bin/env bash
set -Eeuo pipefail

# Run during image builds only. Never patch a running game container.
export DEBIAN_FRONTEND=noninteractive
manifest=${1:-/usr/local/share/project-zomboid/apt-packages.txt}
apt-get update
# Include dependency additions required for vendor fixes, without removing packages.
apt-get -y --no-install-recommends upgrade --with-new-pkgs

# Optional explicit upgrades for reviewed advisories. Bare packages use the
# latest available binary; package=version requires an exact binary version;
# package>=version requires a minimum Debian source version. Refuse new
# packages and downgrades; missing vendor fixes must fail visibly.
targets=()
target_packages=()
prior_binary_versions=()
guard_packages=()
guard_minimums=()
apt_target_re='^([a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?)(=([a-zA-Z0-9.+:~_-]+))?$'
source_guard_re='^([a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?)>=([a-zA-Z0-9.+:~_-]+)$'
while IFS= read -r line || [[ -n "$line" ]]; do
  line=${line%%#*}
  read -r -a fields <<< "$line"
  [[ ${#fields[@]} -eq 0 ]] && continue
  [[ ${#fields[@]} -eq 1 ]] || {
    printf 'Invalid APT target: %s\n' "$line" >&2; exit 1;
  }
  target=${fields[0]}
  minimum=''
  exact=''
  if [[ "$target" =~ $source_guard_re ]]; then
    package=${BASH_REMATCH[1]}
    minimum=${BASH_REMATCH[3]}
    dpkg --validate-version "$minimum" >/dev/null || {
      printf 'Invalid Debian source version: %s\n' "$minimum" >&2; exit 1;
    }
  elif [[ "$target" =~ $apt_target_re ]]; then
    package=${BASH_REMATCH[1]}
    exact=${BASH_REMATCH[4]:-}
    if [[ -n "$exact" ]]; then
      dpkg --validate-version "$exact" >/dev/null || {
        printf 'Invalid Debian binary version: %s\n' "$exact" >&2; exit 1;
      }
    fi
  else
    printf 'Invalid APT target: %s\n' "$line" >&2; exit 1
  fi
  [[ $(dpkg-query -W -f='${Status}' "$package") == 'install ok installed' ]] || {
    printf 'APT target is not installed: %s\n' "$package" >&2; exit 1;
  }
  installed_binary=$(dpkg-query -W -f='${Version}' "$package")
  if [[ -n "$exact" ]]; then
    dpkg --compare-versions "$exact" ge "$installed_binary" || {
      printf 'Refusing APT downgrade: %s (%s -> %s)\n' \
        "$package" "$installed_binary" "$exact" >&2; exit 1;
    }
  fi
  target_packages+=("$package")
  prior_binary_versions+=("$installed_binary")
  if [[ -n "$minimum" ]]; then
    targets+=("$package")
    guard_packages+=("$package")
    guard_minimums+=("$minimum")
  else
    targets+=("$target")
  fi
done < "$manifest"
if (( ${#targets[@]} )); then
  apt-get install -y --no-install-recommends --only-upgrade "${targets[@]}"
fi
for i in "${!target_packages[@]}"; do
  package=${target_packages[$i]}
  installed=$(dpkg-query -W -f='${Version}' "$package")
  dpkg --compare-versions "$installed" ge "${prior_binary_versions[$i]}" || {
    printf 'APT target was downgraded: %s (%s -> %s)\n' \
      "$package" "${prior_binary_versions[$i]}" "$installed" >&2; exit 1;
  }
done
for i in "${!guard_packages[@]}"; do
  package=${guard_packages[$i]}
  minimum=${guard_minimums[$i]}
  installed=$(dpkg-query -W -f='${source:Version}' "$package")
  [[ -n "$installed" ]] || {
    printf 'Debian source version is unavailable for %s\n' "$package" >&2; exit 1;
  }
  dpkg --compare-versions "$installed" ge "$minimum" || {
    printf 'Debian source version is below required minimum: %s (%s < %s)\n' \
      "$package" "$installed" "$minimum" >&2; exit 1;
  }
done
mkdir -p /usr/local/share/project-zomboid
dpkg-query -W -f='${binary:Package}\t${Version}\n' \
  > /usr/local/share/project-zomboid/apt-inventory.tsv
apt-get clean
rm -rf /var/lib/apt/lists/*
