#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -gt 0 ]] || { printf 'Usage: console.sh <command> [arguments...]\n' >&2; exit 2; }
[[ -p "${RUN_DIR:-/run/zomboid}/console" ]] || { printf 'Server console unavailable\n' >&2; exit 1; }
# Bound the write if the server no longer consumes its console.
# shellcheck disable=SC2016 # Positional parameters belong to the inner bash.
timeout 5 bash -c 'printf "%s\n" "$1" > "$2"' _ "$*" "${RUN_DIR:-/run/zomboid}/console"
