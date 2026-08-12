import json
import os
import sqlite3
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None


def resolve_gamertags(xuids):
    requested = {str(xuid) for xuid in xuids}
    resolved = {}

    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\XboxLive") as key:
                xuid = str(winreg.QueryValueEx(key, "Xuid")[0])
                if xuid in requested:
                    for value_name in ("UniqueModernGamertag", "ModernGamertag", "Gamertag"):
                        try:
                            gamertag = str(winreg.QueryValueEx(key, value_name)[0]).strip()
                        except OSError:
                            continue
                        if gamertag:
                            resolved[xuid] = gamertag
                            break
        except OSError:
            pass

    unresolved = requested - resolved.keys()
    cache_path = Path(os.environ.get("LOCALAPPDATA", "")) / (
        r"Packages\Microsoft.GamingApp_8wekyb3d8bbwe\LocalState\AsyncCache.db"
    )
    if unresolved and cache_path.is_file():
        try:
            connection = sqlite3.connect(f"{cache_path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.1)
            try:
                for xuid in unresolved:
                    row = connection.execute(
                        "SELECT value FROM AsyncCache "
                        "WHERE scope = 'user_profile' AND scopeVersion = 1 AND key = ?",
                        (xuid,),
                    ).fetchone()
                    if not row:
                        continue
                    profile = json.loads(row[0])
                    if str(profile.get("xuid")) != xuid:
                        continue
                    gamertag = profile.get("gamertag") or {}
                    display_name = gamertag.get("uniqueGamertag") or gamertag.get("legacyGamertag")
                    if isinstance(display_name, str) and display_name.strip():
                        resolved[xuid] = display_name.strip()
            finally:
                connection.close()
        except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
            pass

    return resolved
