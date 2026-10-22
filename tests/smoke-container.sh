#!/usr/bin/env bash
set -Eeuo pipefail
image=${1:-project-zomboid:local}
name="pz-smoke-${RANDOM}"
cleanup() { docker rm -fv "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
password=$(openssl rand -hex 24)
if [[ -n "${GITHUB_ACTIONS:-}" ]]; then printf '::add-mask::%s\n' "$password"; fi
docker run --rm --entrypoint bash "$image" -c \
  'test "$(id -u)" = 10000 && test -x /opt/steamcmd-seed/steamcmd.sh && test -x /lib/ld-linux.so.2'
docker run --detach --name "$name" --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --memory 6g \
  --tmpfs /home/steam:uid=10000,gid=10000,mode=0700,exec \
  --tmpfs /tmp:uid=10000,gid=10000,mode=1777 \
  --tmpfs /run/zomboid:uid=10000,gid=10000,mode=0700 \
  --mount type=volume,destination=/server \
  --mount type=volume,destination=/data \
  --env "ADMIN_PASSWORD=$password" --env MIN_MEMORY=1g --env MAX_MEMORY=3g \
  --env PUBLIC=false "$image"
ready=false
diagnose_boot() {
  docker logs --tail 120 "$name"
  printf '\nDownloaded launcher and SQLite files:\n'
  docker run --rm --volumes-from "$name" --entrypoint sh "$image" -c '
    sed -n "1,160p" /server/start-server.sh
    find /server -maxdepth 5 \( -iname "*sqlite*" -o -iname "*jdbc*" \) -print
    ls -la /server/linux64 /server/natives 2>/dev/null || true
  ' || true
}
for (( attempt=0; attempt<180; attempt++ )); do
  if [[ $(docker inspect --format '{{.State.Running}}' "$name") != true ]]; then
    diagnose_boot; exit 1
  fi
  if docker exec "$name" /usr/local/bin/healthcheck.sh; then ready=true; break; fi
  sleep 10
done
if [[ "$ready" != true ]]; then diagnose_boot; exit 1; fi
printf 'Native game server bound both UDP ports.\n'
# Send a command through the same console used for graceful shutdown.
docker exec "$name" /usr/local/bin/console.sh save
docker exec "$name" test -f /data/db/servertest.db
sleep 10
docker stop --time 180 "$name" >/dev/null
[[ $(docker inspect --format '{{.State.ExitCode}}' "$name") == 0 ]]
docker logs "$name" 2>&1 | grep -F 'Sending console save and quit'
printf 'Game installation, readiness and save/quit smoke checks passed.\n'
