#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/bin"
export REAL_DPKG
REAL_DPKG=$(command -v dpkg || true)

# Run the real script with only its absolute inventory destination redirected.
# Mutating commands are mocked; version syntax uses real dpkg when available.
sed "s|/usr/local/share/project-zomboid/apt-inventory.tsv|$scratch/apt-inventory.tsv|" \
  "$root/scripts/security-updates.sh" > "$scratch/security-updates.sh"

cat > "$scratch/bin/apt-get" <<'MOCK'
#!/usr/bin/env bash
printf 'apt-get %s\n' "$*" >> "$MOCK_LOG"
MOCK

cat > "$scratch/bin/dpkg-query" <<'MOCK'
#!/usr/bin/env bash
printf 'dpkg-query %s\n' "$*" >> "$MOCK_LOG"
case "$2" in
  '-f=${Status}') printf 'install ok installed' ;;
  '-f=${Version}') printf '%s' "$MOCK_BINARY_VERSION" ;;
  '-f=${source:Version}') printf '%s' "$MOCK_SOURCE_VERSION" ;;
  '-f=${binary:Package}\t${Version}\n') printf 'libfoo\t%s\n' "$MOCK_BINARY_VERSION" ;;
  *) printf 'Unexpected dpkg-query format: %s\n' "$2" >&2; exit 2 ;;
esac
MOCK

cat > "$scratch/bin/dpkg" <<'MOCK'
#!/usr/bin/env bash
printf 'dpkg %s\n' "$*" >> "$MOCK_LOG"
case "$1" in
  --validate-version)
    if [[ -n "$REAL_DPKG" ]]; then
      "$REAL_DPKG" "$@"
    else
      [[ $# -eq 2 && "$2" =~ ^[0-9]+$ ]]
    fi
    ;;
  --compare-versions)
    [[ "$2" =~ ^[0-9]+$ && "$3" == ge && "$4" =~ ^[0-9]+$ ]] || exit 2
    (( 10#$2 >= 10#$4 ))
    ;;
  *) printf 'Unexpected dpkg operation: %s\n' "$1" >&2; exit 2 ;;
esac
MOCK

cat > "$scratch/bin/mkdir" <<'MOCK'
#!/usr/bin/env bash
[[ "$*" == '-p /usr/local/share/project-zomboid' ]]
MOCK

cat > "$scratch/bin/rm" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == '-rf' && "$2" == /var/lib/apt/lists/* ]]
MOCK
chmod +x "$scratch/bin/"*

run_case() {
  local binary=$1 source=$2 entry=$3 expected=$4
  printf '%s\n' "$entry" > "$scratch/apt-packages.txt"
  : > "$scratch/commands.log"
  if MOCK_LOG="$scratch/commands.log" MOCK_BINARY_VERSION="$binary" \
    MOCK_SOURCE_VERSION="$source" PATH="$scratch/bin:$PATH" \
    bash "$scratch/security-updates.sh" "$scratch/apt-packages.txt" \
    > "$scratch/output.log" 2>&1; then
    actual=0
  else
    actual=$?
  fi
  if [[ "$actual" -ne "$expected" ]]; then
    printf 'Unexpected exit code for %s: got %s, expected %s\n' \
      "$entry" "$actual" "$expected" >&2
    cat "$scratch/output.log" >&2
    exit 1
  fi
}

run_case 3 2 'libfoo>=2' 0
grep -Fq 'apt-get install -y --no-install-recommends --only-upgrade libfoo' \
  "$scratch/commands.log"
grep -Fq "dpkg-query -W -f=\${source:Version} libfoo" "$scratch/commands.log"
grep -Fq 'dpkg --compare-versions 2 ge 2' "$scratch/commands.log"
test -s "$scratch/apt-inventory.tsv"

run_case 3 1 'libfoo>=2' 1
grep -Fq 'Debian source version is below required minimum' "$scratch/output.log"
grep -Fq 'dpkg --compare-versions 1 ge 2' "$scratch/commands.log"

run_case 2 2 'libfoo=2' 0
grep -Fq 'dpkg --validate-version 2' "$scratch/commands.log"

run_case 2 2 'libfoo=1' 1
grep -Fq 'Refusing APT downgrade' "$scratch/output.log"
if grep -Fq 'apt-get install' "$scratch/commands.log"; then
  printf 'Downgrade reached apt-get install\n' >&2
  exit 1
fi

printf 'APT security-update guards passed.\n'
