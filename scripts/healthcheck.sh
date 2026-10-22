#!/usr/bin/env bash
set -Eeuo pipefail
# Readiness checks kernel UDP bindings, not just a live launcher process.
# This does not prove game protocol responsiveness or external reachability.
python3 - <<'PY'
import os
from pathlib import Path
required = {int(os.getenv("GAME_PORT", "16261")), int(os.getenv("DIRECT_PORT", "16262"))}
bound = set()
for name in ("/proc/net/udp", "/proc/net/udp6"):
    path = Path(name)
    if path.exists():
        for line in path.read_text().splitlines()[1:]:
            bound.add(int(line.split()[1].rsplit(":", 1)[1], 16))
raise SystemExit(0 if required <= bound else 1)
PY
