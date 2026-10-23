# Security maintenance

The base is `debian:trixie-slim` (Debian 13 stable). A small maintained base,
limited package set, native execution, non-root runtime and regular vendor
updates are the security choices here. This is not a claim that Debian is
universally stronger than a supported Ubuntu LTS.

## APT vulnerability fixes

`scripts/security-updates.sh` runs as root during the image build. It refreshes
indexes and upgrades all installed packages with available Debian fixes.
The build does not add third-party APT repositories or mix Debian releases.

The daily Security patches workflow scans the published `latest` image. If
Trivy reports a fixable High/Critical Debian OS package vulnerability and the
configured APT repositories offer a suitable upgrade, the workflow updates the
managed section of `security/apt-packages.txt` where needed and dispatches a
fresh Container build. A bare manual package target already requests the latest
APT version. A bot commit alone does not trigger a push workflow. The new build pulls
the base, bypasses the runtime cache, rescans, and smoke-tests before publishing.
The full scan and patch decision are retained as a workflow artifact. A fixable
finding without an applicable APT upgrade makes this workflow fail for review.

For manual patching:

1. Inspect the JSON report and the
   [Debian Security Tracker](https://security-tracker.debian.org/tracker/).
2. Rebuild with `make security-build` or run the Container workflow to pick up
   available Debian fixes.
3. Add an **already installed** binary package outside the managed section of
   `security/apt-packages.txt` for an explicit advisory requirement. Use
   `package>=source-version` for a durable minimum guard, or `package=version`
   only when an exact binary version is required and available. Include the
   advisory link and rationale above manual entries. The build refuses absent
   packages, unavailable versions and downgrades.
4. Verify the rebuilt image's scan and redeploy its digest.

All upgrades use the configured signed Debian repositories, including the base
image's `trixie-security` source. The script applies available updates from all
configured Debian suites; it is not limited to the security pocket. The package
inventory is `/usr/local/share/project-zomboid/apt-inventory.tsv` in the image.
Do not add random CVE identifiers or force unverified versions to silence scans.

## Scan policy and limits

CI saves a JSON report containing all severities and unfixed vulnerabilities.
It blocks publication when a High/Critical finding has a reported fixed version.
An unfixed finding still requires review even when publication is allowed.
The scan covers OS/library files in the built image, including the SteamCMD
bootstrap where detected. It cannot fully analyze every proprietary binary.

The installed game, bundled JVM, Steam client's self-updates and Workshop mods
live in volumes and are downloaded after image creation. They are **not covered
by the build image scan**. Updating Debian does not repair those components;
update the relevant Steam branch, review upstream fixes and remove unsafe mods.
CI smoke testing proves startup/shutdown behavior, not absence of vulnerabilities.

Valve's HTTPS bootstrap archive is checksum-pinned. If Valve replaces it, the
build fails until a maintainer reviews the new archive and updates
`STEAMCMD_SHA256` in the Dockerfile. SteamCMD subsequently self-updates under the
unprivileged Steam user using Valve's distribution mechanism.

GitHub Actions are pinned to commits; Dependabot proposes updates. The built
image is scanned and tested locally on the runner before any registry tag is
pushed. Docker load/push uses one platform and does not attach BuildKit SBOM or
provenance attestations; the scan report is retained as an Actions artifact.

## Runtime

The chart runs UID/GID 10000, drops all Linux capabilities, prevents privilege
escalation, uses RuntimeDefault seccomp and a read-only root filesystem, and
does not mount a Kubernetes API token. Writable server/data volumes and Steam's
temporary home are required. RCON is not configured or exposed. NetworkPolicy
is left to the cluster operator because Steam/Workshop download endpoints are
dynamic; restrict ingress to your players/VPN when possible.

Protect Kubernetes Secrets, Helm release records, world data and first-boot logs.
The game may log its initial admin-password argument. Rotate that password using
the game after first login, and restrict log access. The chart requires a Secret
with no built-in default password.

Report vulnerabilities using the repository's private GitHub security reporting
feature if enabled. Do not include working credentials or private worlds in a
public issue.
