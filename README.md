# Project Zomboid

Native Linux x86_64 dedicated server container and Kubernetes Helm chart. Uses
Valve SteamCMD with anonymous login to install app **380870**, then runs the
game's supplied **`start-server.sh`** and bundled JVM. Steam integration stays
enabled. The default is Steam's **public** branch; betas require an explicit
`STEAM_BRANCH` / `server.steamBranch` selection. Clients must use the same build.

## Quick start: Kubernetes

Requirements: Linux AMD64 worker, Kubernetes 1.27+, Helm 3, a default storage
class (or existing PVCs), and a UDP-capable LoadBalancer. The default requests
2 CPUs / 4 GiB RAM and limits the pod to 4 CPUs / 6 GiB RAM, with a 4 GiB
maximum Java heap. This profile is intended for an 8 GiB, 4-vCPU node.
First boot downloads several GB of game files and needs outbound Steam access.

```bash
git clone https://github.com/zhmarvi/project-zomboid.git
cd project-zomboid
kubectl create namespace zomboid

# Generate a secret without putting the password in shell history or Helm values.
umask 077
openssl rand -hex 24 > admin-password.local
kubectl -n zomboid create secret generic zomboid-admin \
  --from-file=admin-password=admin-password.local

helm upgrade --install zomboid ./charts/project-zomboid \
  --namespace zomboid --values examples/values.yaml

kubectl -n zomboid logs -f zomboid-project-zomboid-0
kubectl -n zomboid get svc zomboid-project-zomboid
```

Connect from the game's Join/Favorites menu to the service's external IP, port
**16261**. Forward **UDP 16261 and 16262** through host/network firewalls and
your router when applicable. No HTTP ingress or RCON exposure is required.

For bare metal, provide a UDP-capable LoadBalancer. Alternatively, set
`hostNetwork=true` and `service.type=ClusterIP`, pin the pod to a chosen AMD64
node using `nodeSelector`, and connect to that node's IP. Only one server may
use these ports per node. A NodePort example is in the
[chart guide](charts/project-zomboid/README.md); its translated external ports
need careful forwarding for direct-connect traffic.

## Local Docker / Compose

On an x86_64 Docker host:

```bash
umask 077
openssl rand -hex 24 > admin-password.local
export ADMIN_PASSWORD_FILE="$PWD/admin-password.local"
docker compose up --build -d
docker compose logs -f
docker compose down
```

Named volumes retain `/server` and `/data`. Do not run `docker compose down -v`
unless you intend to delete the world. The Compose service runs with a read-only
root filesystem, dropped capabilities, writable temporary home, and 180 seconds
for shutdown. `make build` produces a local AMD64 image via Docker Buildx.

## Configuration

| Environment variable | Default / purpose |
| --- | --- |
| `STEAM_BRANCH` | `public`; `unstable` opts into the beta when available |
| `UPDATE_ON_START` | `true`; `false` reuses an existing install, but an empty `/server` always installs |
| `VALIDATE_ON_UPDATE` | `true`; Steam validates files during updates |
| `SERVER_NAME` | `servertest`; filename/world identity, letters/digits/underscore/hyphen |
| `ADMIN_USERNAME` | `admin`; first database creation only |
| `ADMIN_PASSWORD_FILE` | Read bootstrap password from this mounted file |
| `ADMIN_PASSWORD` | Alternative bootstrap password; file takes precedence |
| `MIN_MEMORY` / `MAX_MEMORY` | `1g` / `4g`; supplied to the upstream launcher before `--` |
| `GAME_PORT` / `DIRECT_PORT` | `16261` / `16262`, UDP |
| `SERVER_IP` | Optional bind address; chart uses the pod IP |
| `SHUTDOWN_TIMEOUT` | `150` seconds before TERM fallback, then KILL after 5 more seconds |
| `PUBLIC_NAME` / `PUBLIC` | Display name / listing status; chart defaults to unlisted |
| `SERVER_PASSWORD` | Optional player join password; stored in the persisted INI |
| `MAX_PLAYERS`, `PVP`, `PAUSE_EMPTY` | Optional INI overrides; chart defaults 16, false, true |
| `AUTOSAVE_INTERVAL` | Minutes between saves; chart default 15 |
| `BACKUPS_COUNT` / `BACKUPS_PERIOD` | Game backup count / period in minutes; chart defaults 5 / 120 |
| `MOD_IDS` / `WORKSHOP_IDS` | Quoted semicolon-separated mod names / Steam Workshop IDs |
| `MAP_NAMES` | Ordered semicolon-separated maps; include `Muldraugh, KY` last as appropriate |
| `STEAM_VAC` | `true` or `false`; chart defaults to true |

In Helm, optional INI overrides live under `server.settings` as **quoted strings**.
Only explicitly provided settings are rewritten. Other INI entries, comments,
Lua sandbox/spawn settings, and manually managed mods are preserved. An explicit
empty `MOD_IDS` / `WORKSHOP_IDS` clears that list. To stop Helm managing a default
key, set it to `null` in your override file. Keep player passwords in a securely
managed INI on the PVC if you want to avoid Helm release/ConfigMap storage.

The launcher generates missing settings on the first start; no fixed sleep or
throwaway game start is needed for configuration generation.

## Persistence, commands, and updates

| Path | Purpose |
| --- | --- |
| `/server` | Steam installation, manifests, bundled JVM, downloaded Workshop files |
| `/data` | World saves, INI/Lua configuration, player/admin database, logs and backups |
| `/home/steam` | Disposable Steam client/cache; chart mounts an `emptyDir` |

The chart runs one StatefulSet replica and retains its PVCs on uninstall. Keep
the Helm release name, namespace, `server.name`, and claims stable to retain
world identity. Imported storage must be writable by UID/GID **10000:10000**;
`fsGroup` handles supported CSI volumes, but root-squashed NFS may need preparation
on the storage server. Increasing an existing volumeClaimTemplate's size through
a Helm upgrade may be rejected by Kubernetes; expand the PVC through your
storage provider's supported procedure instead.

```bash
# Local game console access, without opening an RCON TCP service:
kubectl -n zomboid exec zomboid-project-zomboid-0 -- console.sh save
kubectl -n zomboid exec zomboid-project-zomboid-0 -- console.sh players

# Restart to update the Steam public branch (when UPDATE_ON_START=true):
kubectl -n zomboid rollout restart statefulset/zomboid-project-zomboid
```

SIGTERM sends console `save` and `quit`, waits for the server to exit, and uses a
bounded fallback. Kubernetes gets 180 seconds. Readiness checks both UDP kernel
bindings; it does not guarantee application responsiveness or internet
reachability. Liveness restarts are deliberately disabled during downloads,
long world loads, and saves.

Stop the server and snapshot/copy `/data` before branch changes, game updates,
or restoring backups. Game backups on the same PVC are not disaster recovery.
Keep a separate backup outside the cluster/storage device. Pin the image by
digest for repeatable deployments and set `server.updateOnStart=false` to avoid
changing an existing game install on every restart. Changing the branch then
requires an explicit update; changing image tags alone doesn't replace game
files already on the PVC.

## Image publishing and security updates

The Container workflow validates scripts and Helm, builds **linux/amd64** on a
native GitHub runner, pulls a fresh Debian base, upgrades installed APT packages,
generates a complete Trivy report, rejects **fixable High/Critical** findings,
and smoke-tests the native game server before publishing the tested image.
Pull requests run the checks without publishing. Pushes to `main`, `v*` tags,
manual dispatch, and weekly scheduled runs can publish to:

```text
ghcr.io/zhmarvi/project-zomboid:latest
ghcr.io/zhmarvi/project-zomboid:sha-<full-commit>
ghcr.io/zhmarvi/project-zomboid:build-<UTC-timestamp>
```

Version tags also publish SemVer tags. Timestamp tags identify rebuilds of the
same Git commit; deployments should pin the resulting digest. Rebuilds do not
restart your cluster automatically.

The Security patches workflow scans the published image daily. For fixable
High/Critical Debian package findings with an available APT update, it records
minimum source versions in `security/apt-packages.txt` where needed and starts
a fresh Container build. An existing bare package target already requests the
newest APT version. The build must pass its own scan and smoke test before it
publishes an image. Findings that APT cannot fix remain in the report for review.

Read [SECURITY.md](SECURITY.md) for patching instructions and the scope of the
scan. APT updates cannot fix proprietary game/JVM/Steam libraries downloaded at
runtime, and vendor-unfixed CVEs remain in the report. No distribution or image
is guaranteed CVE-free.

## Validation

```bash
# Requires Python 3, Bash, ShellCheck, yamllint, Helm 3.
make validate

# Requires Docker on native AMD64; downloads and launches the game:
make build
./tests/smoke-container.sh project-zomboid:local
```

Tests cover INI preservation/injection rejection, password bootstrap, Steam
arguments, console shutdown, vulnerability gating, and Helm rendering modes.
There is no ARM emulation, Box64, or DepotDownloader in this repository.
