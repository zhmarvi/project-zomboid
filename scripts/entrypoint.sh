#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${SERVER_DIR:=/server}" "${DATA_DIR:=/data}" "${RUN_DIR:=/run/zomboid}"
: "${STEAMCMD_DIR:=$HOME/steamcmd}" "${STEAMCMD_SEED:=/opt/steamcmd-seed}"
: "${SERVER_NAME:=servertest}" "${ADMIN_USERNAME:=admin}"
: "${MIN_MEMORY:=1g}" "${MAX_MEMORY:=4g}" "${SHUTDOWN_TIMEOUT:=150}"
: "${UPDATE_ON_START:=true}" "${VALIDATE_ON_UPDATE:=true}" "${STEAM_BRANCH:=public}"
export SERVER_DIR DATA_DIR RUN_DIR SERVER_NAME

log() { printf '[zomboid] %s\n' "$*"; }
fail() { log "$*" >&2; exit 1; }
[[ "$MIN_MEMORY" =~ ^[1-9][0-9]*[mMgG]$ && "$MAX_MEMORY" =~ ^[1-9][0-9]*[mMgG]$ ]] || fail 'Memory must use m or g, e.g. 1g and 4g.'
[[ "$SHUTDOWN_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || fail 'SHUTDOWN_TIMEOUT must be a positive integer.'
[[ "$STEAM_BRANCH" =~ ^[A-Za-z0-9_-]+$ ]] || fail 'Invalid STEAM_BRANCH.'
for flag in "$UPDATE_ON_START" "$VALIDATE_ON_UPDATE"; do
  [[ "$flag" == true || "$flag" == false ]] || fail 'Update flags must be true or false.'
done

mkdir -p "$SERVER_DIR" "$DATA_DIR" "$RUN_DIR" "$STEAMCMD_DIR" "$HOME/.steam/sdk64"
python3 "${CONFIGURE_SCRIPT:-/usr/local/lib/project-zomboid/configure.py}"

child_pid=''
phase=update
stopping=false
# shellcheck disable=SC2317,SC2329 # Invoked by TERM/INT traps.
shutdown() {
  [[ "$stopping" == false ]] || return 0
  stopping=true
  trap '' TERM INT
  shutdown_status=0
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    if [[ "$phase" == game ]]; then
      log 'Sending console save and quit; waiting for world shutdown.'
      printf 'save\nquit\n' >&3
    else
      log 'Stopping SteamCMD.'
      kill -TERM -- "-$child_pid" 2>/dev/null || true
    fi
    # A separate watchdog enforces a bound without abandoning an interrupted wait.
    (
      sleep "$SHUTDOWN_TIMEOUT"
      kill -TERM -- "-$child_pid" 2>/dev/null || true
      sleep 5
      kill -KILL -- "-$child_pid" 2>/dev/null || true
    ) &
    watchdog=$!
    wait "$child_pid" || shutdown_status=$?
    kill "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
  fi
  [[ "$phase" == update ]] && exit 0
  exit "$shutdown_status"
}
trap shutdown TERM INT

if [[ "$UPDATE_ON_START" == true || ! -f "$SERVER_DIR/start-server.sh" ]]; then
  if [[ ! -x "$STEAMCMD_DIR/steamcmd.sh" ]]; then
    cp -R "$STEAMCMD_SEED/." "$STEAMCMD_DIR/"
  fi
  steam_args=(+force_install_dir "$SERVER_DIR" +login anonymous +app_update 380870)
  if [[ "$STEAM_BRANCH" != public ]]; then steam_args+=(-beta "$STEAM_BRANCH"); fi
  if [[ "$VALIDATE_ON_UPDATE" == true ]]; then steam_args+=(validate); fi
  steam_args+=(+quit)
  installed=false
  for attempt in 1 2 3; do
    log "Installing/updating Steam app 380870 ($STEAM_BRANCH), attempt $attempt."
    setsid "$STEAMCMD_DIR/steamcmd.sh" "${steam_args[@]}" &
    child_pid=$!
    if wait "$child_pid"; then installed=true; break; fi
    child_pid=''
    if (( attempt < 3 )); then sleep 10; fi
  done
  child_pid=''
  [[ "$installed" == true ]] || fail 'SteamCMD failed; refusing to launch a possibly incomplete installation.'
fi
[[ -f "$SERVER_DIR/start-server.sh" ]] || fail 'The supplied start-server.sh is missing.'

# Some Steam depots omit SQLite's native JNI library even though the supplied
# launcher points its JDBC loader at linux64/. Prefer the Steam copy when present.
if [[ ! -e "$SERVER_DIR/linux64/libsqlitejdbc.so" ]]; then
  mkdir -p "$SERVER_DIR/linux64"
  ln -sfn /usr/lib/x86_64-linux-gnu/jni/libsqlitejdbc.so "$SERVER_DIR/linux64/libsqlitejdbc.so"
fi

if [[ -f "$STEAMCMD_DIR/linux64/steamclient.so" ]]; then
  ln -sfn "$STEAMCMD_DIR/linux64/steamclient.so" "$HOME/.steam/sdk64/steamclient.so"
elif [[ -f "$SERVER_DIR/linux64/steamclient.so" ]]; then
  ln -sfn "$SERVER_DIR/linux64/steamclient.so" "$HOME/.steam/sdk64/steamclient.so"
fi

args=("-Xms$MIN_MEMORY" "-Xmx$MAX_MEMORY" -- "-cachedir=$DATA_DIR" -servername "$SERVER_NAME")
if [[ -n "${SERVER_IP:-}" ]]; then args+=(-ip "$SERVER_IP"); fi
if [[ ! -f "$DATA_DIR/db/$SERVER_NAME.db" ]]; then
  if [[ -n "${ADMIN_PASSWORD_FILE:-}" ]]; then ADMIN_PASSWORD=$(<"$ADMIN_PASSWORD_FILE"); fi
  [[ -n "${ADMIN_PASSWORD:-}" && "$ADMIN_PASSWORD" != *$'\n'* && "$ADMIN_PASSWORD" != *$'\r'* ]] || fail 'Set ADMIN_PASSWORD_FILE or ADMIN_PASSWORD for the first launch.'
  # Upstream may log launch arguments. Only supply the bootstrap secret until DB exists.
  args+=(-adminusername "$ADMIN_USERNAME" -adminpassword "$ADMIN_PASSWORD")
fi
unset ADMIN_PASSWORD

# start-server.sh sets up the bundled JVM/native libraries. Keep that upstream flow.
export LD_LIBRARY_PATH="$SERVER_DIR/jre64/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fifo="$RUN_DIR/console"
rm -f "$fifo"
mkfifo -m 600 "$fifo"
exec 3<>"$fifo"
phase=game
cd "$SERVER_DIR"
log 'Starting the supplied Linux server launcher.'
setsid bash ./start-server.sh "${args[@]}" "$@" <&3 &
child_pid=$!
printf '%s\n' "$child_pid" > "$RUN_DIR/server.pid"
status=0
wait "$child_pid" || status=$?
rm -f "$RUN_DIR/server.pid" "$fifo"
exit "$status"
