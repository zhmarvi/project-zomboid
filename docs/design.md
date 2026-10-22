# Design and references

This project targets Linux x86_64 directly. SteamCMD uses its 32-bit runtime
support, and Project Zomboid uses its native 64-bit binaries and bundled JVM.

The [PZ dedicated-server guide](https://pzwiki.net/wiki/Dedicated_server) describes
anonymous SteamCMD app 380870 installation, an unprivileged server account, the
supplied `start-server.sh`, the default UDP ports and console shutdown. The
[Valve SteamCMD guide](https://developer.valvesoftware.com/wiki/SteamCMD) describes
the SteamCMD installation/distribution mechanism. Steam public and beta releases
change independently of this container; the chart version is not a game version.

Reviewed references:

| Source | Influence |
| --- | --- |
| [zhmarvi/valheim-arm64](https://github.com/zhmarvi/valheim-arm64) | Top-level Dockerfile, scripts, Helm chart, Compose and package-refresh workflow layout |
| [danixu86 image](https://hub.docker.com/r/danixu86/project-zomboid-dedicated-server) and [source](https://github.com/Danixu/project-zomboid-server-docker) | Supplied launcher, JVM arguments before `--`, persistent INI management and console shutdown |
| [jsknnr/project-zomboid-server](https://github.com/jsknnr/project-zomboid-server) | Non-root identity, separate install/data storage, environment settings and Steam branch selection |
| [Debian stable release](https://www.debian.org/releases/stable/) | Debian 13 slim base; i386 support libraries remain available for AMD64 |

The runtime installs the game at first launch instead of redistributing game
files in the image. Existing game installs persist across image upgrades. Startup
updates fail closed after three attempts. The image runs the upstream launcher
rather than hardcoding its classpath, JVM version or Java invocation.

A single StatefulSet prevents normal rolling updates from intentionally running
two writers against one world. Do not force-delete a pod on an unreachable node
until you have fenced the old process; Kubernetes cannot protect against two
servers writing shared storage after an unsafe manual recovery.

Port readiness is deliberately weaker than a game-protocol probe. A bound UDP
socket is observable without exposing an RCON password, but it does not prove
that a player can join. Verify from an actual client after deployment.
