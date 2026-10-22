"""Merge explicitly managed settings, preserving other INI settings and comments."""
import os
import re
from pathlib import Path

SETTINGS = {
    "GAME_PORT": "DefaultPort", "DIRECT_PORT": "UDPPort",
    "PUBLIC_NAME": "PublicName", "PUBLIC": "Public", "SERVER_PASSWORD": "Password",
    "MAX_PLAYERS": "MaxPlayers", "PVP": "PVP", "PAUSE_EMPTY": "PauseEmpty",
    "AUTOSAVE_INTERVAL": "SaveWorldEveryMinutes", "BACKUPS_COUNT": "BackupsCount",
    "BACKUPS_PERIOD": "BackupsPeriod", "MOD_IDS": "Mods",
    "WORKSHOP_IDS": "WorkshopItems", "MAP_NAMES": "Map", "STEAM_VAC": "SteamVAC",
}
BOOLEANS = {"PUBLIC", "PVP", "PAUSE_EMPTY", "STEAM_VAC"}
INTEGERS = {"MAX_PLAYERS", "AUTOSAVE_INTERVAL", "BACKUPS_COUNT", "BACKUPS_PERIOD"}


def merge(text, settings):
    pending = dict(settings)
    output = []
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in settings:
            if key in pending:
                output.append(f"{key}={pending.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in pending.items())
    return "\n".join(output) + "\n"


def configure(env):
    name = env.get("SERVER_NAME", "servertest")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("SERVER_NAME must be 1–64 letters, digits, underscores or hyphens")
    settings = {}
    for variable, key in SETTINGS.items():
        if variable not in env:
            continue
        value = env[variable]
        if any(c in value for c in "\r\n\x00"):
            raise ValueError(f"{variable} must be a single line")
        if variable in BOOLEANS and value not in {"true", "false"}:
            raise ValueError(f"{variable} must be true or false")
        if variable in INTEGERS and (not value.isdecimal() or int(value) < 1):
            raise ValueError(f"{variable} must be a positive integer")
        if variable in {"GAME_PORT", "DIRECT_PORT"}:
            if not value.isdecimal() or not 1024 <= int(value) <= 65535:
                raise ValueError(f"{variable} must be a port between 1024 and 65535")
        settings[key] = value
    if settings.get("DefaultPort") == settings.get("UDPPort") and "DefaultPort" in settings:
        raise ValueError("Game and direct-connect ports must differ")
    path = Path(env.get("DATA_DIR", "/data")) / "Server" / f"{name}.ini"
    path.parent.mkdir(parents=True, exist_ok=True)
    result = merge(path.read_text() if path.exists() else "", settings)
    temporary = path.with_suffix(".ini.tmp")
    temporary.write_text(result)
    temporary.chmod(0o600)
    temporary.replace(path)


if __name__ == "__main__":
    try:
        configure(os.environ)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
