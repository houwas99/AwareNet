# modules/license.py — Système de licence AwareNet (.exe)
# Gère HWID, génération/validation de clé, stockage et vérification online/offline
import os
import re
import hmac
import hashlib
import base64
import json
import platform
import uuid
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────
# Lien externe où l'utilisateur obtient sa clé — LootLabs
LOOTLABS_URL = "https://loot-link.com/s?36ylX3U0"
KEY_URL = os.environ.get("AWARNET_KEY_URL", LOOTLABS_URL)

# LootLabs — mode actif (lien static + validation offline HMAC)
USE_LOOTLABS = os.environ.get("USE_LOOTLABS", "1") not in ("0", "false", "False")
# Legacy Platoboost — désactivé (remplacé par LootLabs), conservé pour compatibilité
USE_PLATOBOOST = False
PLATOBOOST_SERVICE = int(os.environ.get("PLATOBOOST_SERVICE", "30939"))
PLATOBOOST_SECRET = os.environ.get("PLATOBOOST_SECRET", "")

# Serveur custom désactivé (LootLabs seul)
LICENSE_SERVER_URL = ""

_LIC_OBF = "ak0YDh81QEcTH0oUKlRkbD00XEQFMVpnW3oKQWgMQyQWHEtCHBE="
def _lic_deobf(e):
    import base64 as _b
    k = "".join([chr(c) for c in [88,121,57,35,107,80,50,36,118,76,56,113,90,33,55,65]])
    x = _b.b64decode(e.encode())
    b = bytes([x[i] ^ ord(k[i % len(k)]) for i in range(len(x))])
    return b[::-1].decode()
# Offline réactivé pour LootLabs (clé AWARE-... liée HWID)
LICENSE_SECRET = os.environ.get("AWARNET_LICENSE_SECRET") or _lic_deobf(_LIC_OBF)

# Durée de validité de la licence après activation (heures). 24h par défaut.
try:
    LICENSE_DURATION_HOURS = int(os.environ.get("AWARNET_LICENSE_HOURS", "24"))
except Exception:
    LICENSE_DURATION_HOURS = 24
LICENSE_DURATION_SECONDS = LICENSE_DURATION_HOURS * 3600

# ── Platoboost singleton ──────────────────────────────────────────────────
_boost_instance = None
_boost_last_error = ""

def _get_boost():
    global _boost_instance, _boost_last_error
    if not USE_PLATOBOOST:
        return None
    if _boost_instance is not None:
        return _boost_instance
    try:
        from modules.boost import Boost
        def _cb(msg):
            global _boost_last_error
            _boost_last_error = str(msg)
        _boost_instance = Boost(callback=_cb)
        return _boost_instance
    except Exception as e:
        _boost_last_error = str(e)
        return None

def get_platoboost_link() -> str:
    """Retourne le lien Platoboost dynamique (ou KEY_URL fallback)."""
    b = _get_boost()
    if b:
        try:
            link = b.get_link()
            if link:
                return link
        except Exception:
            pass
    return KEY_URL

def get_platoboost_error() -> str:
    return _boost_last_error

# En mode .exe PyInstaller, les fichiers doivent être à côté de l'exe, pas dans le temp _MEIPASS
def _base_dir():
    import sys
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.py")) else "."
    # Toutes les données dans "awarenet ressources"
    res = os.path.join(base, "awarenet ressources")
    try:
        os.makedirs(res, exist_ok=True)
    except Exception:
        pass
    return res

_BASE = _base_dir()
LICENSE_FILE = os.environ.get("AWARNET_LICENSE_FILE", os.path.join(_BASE, "license.key"))
HWID_FILE = os.environ.get("AWARNET_HWID_FILE", os.path.join(_BASE, ".hwid"))

# Bypass pour dev: set AWARNET_NO_LICENSE=1 pour désactiver le check
# En .exe, le bypass est bloqué sauf si .dev présent (protect.is_bypass_allowed)
# En mode source (non frozen), on bypass automatiquement (pas de clé)
BYPASS_ENV = "AWARNET_NO_LICENSE"
def _is_bypass():
    import sys as _sys
    if not getattr(_sys, 'frozen', False):
        return True  # source -> pas de clé, juste mot de passe
    try:
        from modules.protect import is_bypass_allowed
        return is_bypass_allowed()
    except Exception:
        return os.environ.get(BYPASS_ENV) == "1"

# ── HWID ─────────────────────────────────────────────────────────────────
# Fix 2026-09: HWID ne doit PAS dépendre du WiFi/MAC (uuid.getnode change avec WiFi random MAC).
# On utilise MachineGuid Windows (stable) + CPU/BIOS UUID, et on cache dans AppData + exe dir.

def _get_windows_machine_guid() -> str:
    """Récupère MachineGuid Windows (stable, ne change pas avec WiFi)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            guid, _ = winreg.QueryValueEx(k, "MachineGuid")
            if guid:
                return str(guid).strip()
    except Exception:
        pass
    return ""

def _get_wmic_uuid() -> str:
    """UUID BIOS via wmic (stable)."""
    try:
        import subprocess
        # wmic csproduct get UUID est très stable
        out = subprocess.check_output("wmic csproduct get UUID", shell=True, timeout=4, stderr=subprocess.DEVNULL).decode(errors="ignore")
        for line in out.splitlines():
            s = line.strip()
            if s and s.lower() != "uuid" and "-" in s:
                return s.strip()
    except Exception:
        pass
    return ""

def _get_appdata_hwid_path() -> str:
    """Chemin AppData pour HWID persistant même si .exe déplacé."""
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "AwareNet")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, ".hwid")
    except Exception:
        return ""

# Liste des endroits où chercher un HWID déjà cache (ordre priorité)
def _hwid_search_paths():
    paths = []
    # 1. env override
    if HWID_FILE and HWID_FILE not in paths:
        paths.append(HWID_FILE)
    # 2. à côté de l'exe / projet
    legacy = os.path.join(_BASE, ".hwid")
    if legacy not in paths:
        paths.append(legacy)
    # 3. ./ .hwid (cwd)
    cwd_hwid = os.path.join(os.getcwd(), ".hwid")
    if cwd_hwid not in paths:
        paths.append(cwd_hwid)
    # 4. AppData
    ad = _get_appdata_hwid_path()
    if ad and ad not in paths:
        paths.append(ad)
    return paths

def get_hwid() -> str:
    """Génère un HWID stable SANS dépendance WiFi/MAC."""
    # 1. try cached hwid dans tous les endroits connus
    for p in _hwid_search_paths():
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cached = f.read().strip().upper()
                    if re.match(r"^[A-F0-9]{16}$", cached):
                        return cached
            except Exception:
                continue

    # 2. generate stable (sans MAC)
    raw_parts = []
    guid = _get_windows_machine_guid()
    if guid:
        raw_parts.append(guid)
    wmic = _get_wmic_uuid()
    if wmic:
        raw_parts.append(wmic)
    # Toujours ajouter des éléments stables non-réseau
    try:
        raw_parts.append(platform.node() or "")
        raw_parts.append(platform.processor() or "")
        raw_parts.append(platform.machine() or "")
        # getpass.getuser est stable
        try:
            import getpass
            raw_parts.append(getpass.getuser() or "")
        except Exception:
            pass
    except Exception:
        pass

    # Fallback ultime: si tout vide (Linux rare), on prend uuid.getnode en dernier recours seulement
    raw = "|".join([p for p in raw_parts if p])
    if not raw.strip("|"):
        try:
            raw = str(uuid.getnode())
        except Exception:
            raw = "fallback-awarenet-2026"

    try:
        digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest().upper()[:16]
    except Exception:
        digest = hashlib.sha256(str(uuid.getnode()).encode()).hexdigest().upper()[:16]

    # cache dans TOUS les endroits possibles pour stabilité future (même si déjà existe, force sync)
    for p in _hwid_search_paths():
        if not p:
            continue
        try:
            d = os.path.dirname(p)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            # écrit si n'existe pas ou vide
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(digest)
            else:
                # vérifie cohérence, si différent on garde l'existant (ne pas écraser licence active)
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        existing = fh.read().strip().upper()
                    if existing != digest and re.match(r"^[A-F0-9]{16}$", existing):
                        # garde l'ancien HWID pour compatibilité — ne pas écraser
                        digest = existing
                except Exception:
                    pass
        except Exception:
            continue
    return digest


def _get_legacy_hwid() -> str:
    """Ancien HWID basé MAC (pour compatibilité après migration)."""
    try:
        mac = uuid.getnode()
        raw = f"{mac}-{platform.node()}-{platform.machine()}-{platform.processor()}"
        return hashlib.sha256(raw.encode()).hexdigest().upper()[:16]
    except Exception:
        return ""

# ── Format de clé ─────────────────────────────────────────────────────────
# Format offline: AWARE-XXXX-XXXX-XXXX-XXXX  (16 hex chars = 8 bytes HMAC)
# Il est dérivé de HWID + SECRET via HMAC-SHA256

def _hwid_to_key(hwid: str, secret: str = None) -> str:
    """Génère la clé attendue pour un HWID donné (offline)."""
    sec = (secret or LICENSE_SECRET).encode()
    hm = hmac.new(sec, hwid.encode(), hashlib.sha256).hexdigest().upper()
    # prend 16 chars pour former la clé
    core = hm[:16]  # 4 groupes de 4
    groups = [core[i:i+4] for i in range(0, 16, 4)]
    return "AWARE-" + "-".join(groups)

def generate_key_for_hwid(hwid: str = None) -> str:
    """Helper pour toi: génère une clé pour un HWID (à héberger sur ton lien externe)."""
    h = (hwid or get_hwid()).strip().upper()
    return _hwid_to_key(h)

def generate_key_for_current_machine() -> str:
    return generate_key_for_hwid(get_hwid())

# Quelques clés master universelles (optionnel, pour toi)
MASTER_KEYS = set(
    k.strip().upper()
    for k in os.environ.get("AWARNET_MASTER_KEYS", "").split(",")
    if k.strip()
)

# ── Validation ────────────────────────────────────────────────────────────
def _validate_format(key: str) -> bool:
    return bool(re.match(r"^AWARE-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$", key.strip().upper()))

def validate_offline(key: str, hwid: str = None) -> bool:
    key = key.strip().upper()
    if key in MASTER_KEYS:
        return True
    if not _validate_format(key):
        return False
    h = (hwid or get_hwid()).strip().upper()
    expected = _hwid_to_key(h)
    if hmac.compare_digest(key, expected):
        return True
    # Compatibilité: essaie aussi l'ancien HWID MAC-based si différent (migration)
    try:
        legacy = _get_legacy_hwid()
        if legacy and legacy != h:
            if hmac.compare_digest(key, _hwid_to_key(legacy)):
                return True
    except Exception:
        pass
    return False

def validate_online(key: str, hwid: str = None, timeout: int = 8) -> tuple[bool, str]:
    """Valide via serveur externe. Retourne (valid, reason)."""
    if not LICENSE_SERVER_URL:
        return False, "no_server"
    h = (hwid or get_hwid()).strip().upper()
    url = f"{LICENSE_SERVER_URL}?key={key.strip()}&hwid={h}"
    try:
        # utilise urllib pour éviter dépendance requests
        from urllib.request import urlopen, Request
        req = Request(url, headers={"User-Agent": "AwareNet-License/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            # attend {"valid": true} ou {"valid": false, "reason": "..."}
            if data.get("valid") is True or data.get("status") == "valid":
                return True, "ok"
            return False, data.get("reason", "invalid")
    except Exception as e:
        return False, f"server_error: {e}"

def validate_platoboost(key: str) -> tuple[bool, str]:
    """Valide via Platoboost (si activé)."""
    if not USE_PLATOBOOST:
        return False, "platoboost_disabled"
    b = _get_boost()
    if not b:
        return False, f"hors_connexion: platoboost_init_failed {_boost_last_error}"
    try:
        ok = b.verify_key(key.strip())
        if ok:
            return True, "platoboost"
        # Détecte hors connexion via message
        err = (_boost_last_error or "platoboost_invalid").lower()
        if any(x in err for x in ["server error", "failed to", "rate limited", "invalid status", "offline", "connect", "timeout", "timed out", "connection"]):
            # si on a un doute, vérifie si internet est dispo
            try:
                import socket
                socket.create_connection(("8.8.8.8", 53), timeout=3).close()
            except Exception:
                return False, "hors_connexion: vérifiez votre connexion internet"
            return False, f"hors_connexion: {_boost_last_error or 'serveur injoignable'}"
        return False, _boost_last_error or "platoboost_invalid"
    except Exception as e:
        msg = str(e).lower()
        if any(x in msg for x in ["connect", "timeout", "offline", "network", "unreachable"]):
            return False, "hors_connexion: vérifiez votre connexion internet"
        return False, f"platoboost_error: {e}"

def validate_key(key: str, hwid: str = None) -> tuple[bool, str]:
    """
    Valide une clé. Ordre: Platoboost > LICENSE_SERVER_URL > offline HMAC.
    Retourne (valid, reason).
    """
    if not key or not key.strip():
        return False, "empty"
    raw = key.strip()
    # Platoboost FREE_/KEY_ = sensible à la casse (hex lower), on garde tel quel
    if raw.lower().startswith("free_") or raw.lower().startswith("key_"):
        key = raw.strip()
    else:
        key = raw.strip().upper()
    if _is_bypass():
        return True, "bypass"
    if key.upper() in MASTER_KEYS:
        return True, "master"
    # Platoboost seul (offline supprimé)
    ok, reason = validate_platoboost(key)
    if ok:
        return True, reason
    return False, reason

# ── Persistance + Expiration 24h ────────────────────────────────────────
def _activated_file_path() -> str:
    # à côté de license.key
    base = os.path.dirname(LICENSE_FILE) or _BASE
    return os.path.join(base, ".license_activated")

def _appdata_activated_path() -> str:
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "AwareNet")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, ".license_activated")
    except Exception:
        return ""

def _parse_dt(s: str):
    # essaie plusieurs formats
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%H:%M:%S %d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s.strip())
    except Exception:
        return None

def _get_activated_time() -> datetime | None:
    # 1. DB
    try:
        from modules.database import get_global_default
        v = get_global_default("_license_activated_at", "").strip()
        if v:
            dt = _parse_dt(v)
            if dt:
                return dt
    except Exception:
        pass
    # 2. fichier .license_activated (prioritaire)
    for p in [_activated_file_path(), _appdata_activated_path()]:
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    dt = _parse_dt(v)
                    if dt:
                        return dt
            except Exception:
                continue
    # 3. fallback: mtime de license.key
    try:
        p = LICENSE_FILE
        if os.path.exists(p):
            ts = os.path.getmtime(p)
            return datetime.fromtimestamp(ts)
    except Exception:
        pass
    return None

def _set_activated_time(dt: datetime = None):
    dt = dt or datetime.now()
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    # DB
    try:
        from modules.database import set_global_default
        set_global_default("_license_activated_at", iso)
    except Exception:
        pass
    # fichiers (les deux)
    for p in [_activated_file_path(), _appdata_activated_path()]:
        if not p:
            continue
        try:
            d = os.path.dirname(p)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(iso)
        except Exception:
            continue

def get_remaining_seconds() -> int | None:
    """Secondes restantes avant expiration. None si pas activé."""
    dt = _get_activated_time()
    if not dt:
        return None
    elapsed = (datetime.now() - dt).total_seconds()
    remaining = LICENSE_DURATION_SECONDS - int(elapsed)
    return remaining

def is_expired() -> bool:
    """True si licence expirée (24h écoulées)."""
    if _is_bypass():
        return False
    if not load_key():
        return False
    rem = get_remaining_seconds()
    if rem is None:
        return False
    return rem <= 0

def get_expiry_info() -> dict:
    dt = _get_activated_time()
    rem = get_remaining_seconds()
    if dt and rem is not None:
        expires_at = dt.timestamp() + LICENSE_DURATION_SECONDS
        return {
            "activated_at": dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "expires_at": datetime.fromtimestamp(expires_at).strftime("%Y-%m-%dT%H:%M:%S"),
            "remaining_seconds": rem,
            "remaining_hours": round(rem / 3600, 2) if rem > 0 else 0,
            "expired": rem <= 0,
            "duration_hours": LICENSE_DURATION_HOURS,
        }
    return {"activated_at": None, "expires_at": None, "remaining_seconds": None, "remaining_hours": None, "expired": False, "duration_hours": LICENSE_DURATION_HOURS}

def save_key(key: str, path: str = None) -> None:
    p = path or LICENSE_FILE
    raw = key.strip()
    # Platoboost: garde casse d'origine, sinon upper
    if raw.lower().startswith("free_") or raw.lower().startswith("key_"):
        key = raw
    else:
        key = raw.upper()
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(key)
        # cache aussi en DB pour redondance
        try:
            from modules.database import set_global_default
            set_global_default("_license_key", key)
            set_global_default("_license_hwid", get_hwid())
        except Exception:
            pass
        # reset le timer 24h à chaque activation (même clé réutilisée = prolonge 24h)
        _set_activated_time(datetime.now())
    except Exception as e:
        raise IOError(f"Impossible d'écrire {p}: {e}")

def load_key(path: str = None) -> str:
    p = path or LICENSE_FILE
    # 1. fichier
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if "\n" in k:
                    k = k.splitlines()[0].strip()
                # Platoboost: garde casse, sinon upper
                if k.lower().startswith("free_") or k.lower().startswith("key_"):
                    k = k.strip()
                else:
                    k = k.strip().upper()
                if k:
                    return k
        except Exception:
            pass
    # 2. DB fallback
    try:
        from modules.database import get_global_default
        k = get_global_default("_license_key", "").strip()
        if k.lower().startswith("free_") or k.lower().startswith("key_"):
            k = k.strip()
        else:
            k = k.strip().upper()
        if k:
            return k
    except Exception:
        pass
    # 3. env
    env_key = os.environ.get("AWARNET_LICENSE_KEY", "").strip()
    if env_key:
        if env_key.lower().startswith("free_") or env_key.lower().startswith("key_"):
            env_key = env_key.strip()
        else:
            env_key = env_key.strip().upper()
        return env_key
    return ""

def is_licensed(path: str = None) -> bool:
    """Vérifie si une licence valide est présente ET non expirée."""
    if _is_bypass():
        return True
    # anti-debug léger en exe
    try:
        from modules.protect import anti_debug_check, verify_integrity
        if not verify_integrity():
            return False
        anti_debug_check(block=False)
    except Exception:
        pass
    key = load_key(path)
    if not key:
        return False
    ok, _ = validate_key(key)
    if not ok:
        return False
    if is_expired():
        return False
    return ok

def get_license_info(path: str = None) -> dict:
    # En mode source, on est toujours valide (pas de clé)
    if _is_bypass():
        hwid = get_hwid()
        try:
            kurl = get_platoboost_link() if USE_PLATOBOOST else KEY_URL
        except Exception:
            kurl = KEY_URL
        expiry = get_expiry_info()
        return {
            "hwid": hwid, "key": load_key(path), "valid": True, "reason": "bypass_source",
            "expired": False, "key_url": kurl, "key_url_static": KEY_URL,
            "platoboost": USE_PLATOBOOST, "platoboost_error": "", "server_url": LICENSE_SERVER_URL,
            "license_file": path or LICENSE_FILE, "expected_key_preview": "", "duration_hours": LICENSE_DURATION_HOURS, **expiry,
        }
    key = load_key(path)
    if USE_PLATOBOOST:
        try:
            b = _get_boost()
            hwid = b._identifier if b and hasattr(b, '_identifier') else get_hwid()
        except Exception:
            hwid = get_hwid()
    else:
        hwid = get_hwid()
    ok, reason = validate_key(key) if key else (False, "no_key")
    expired = is_expired()
    expiry = get_expiry_info()
    valid = ok and not expired
    if expired and ok:
        reason = "expired"
    try:
        kurl = get_platoboost_link() if USE_PLATOBOOST else KEY_URL
    except Exception:
        kurl = KEY_URL
    return {
        "hwid": hwid,
        "key": key,
        "valid": valid,
        "reason": reason,
        "expired": expired,
        "key_url": kurl,
        "key_url_static": KEY_URL,
        "platoboost": USE_PLATOBOOST,
        "platoboost_error": get_platoboost_error() if USE_PLATOBOOST else "",
        "server_url": LICENSE_SERVER_URL,
        "license_file": path or LICENSE_FILE,
        "expected_key_preview": _hwid_to_key(hwid)[:11] + "***" if not valid else "",
        "duration_hours": LICENSE_DURATION_HOURS,
        **expiry,
    }

def clear_license():
    """Supprime licence (pour test ou logout)."""
    for p in [LICENSE_FILE, _activated_file_path(), _appdata_activated_path()]:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    try:
        from modules.database import get_db
        c = get_db()
        c.execute("DELETE FROM global_defaults WHERE key IN ('_license_key','_license_hwid','_license_activated_at')")
        c.commit()
    except Exception:
        pass

# ── CLI helper ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AwareNet License Tool")
    p.add_argument("--hwid", action="store_true", help="Affiche le HWID")
    p.add_argument("--generate", metavar="HWID", nargs="?", const="__current__", help="Génère une clé pour un HWID (ou machine actuelle)")
    p.add_argument("--validate", metavar="KEY", help="Valide une clé")
    p.add_argument("--check", action="store_true", help="Vérifie license.key présent")
    args = p.parse_args()
    if args.hwid:
        print(get_hwid())
    if args.generate is not None:
        h = None if args.generate == "__current__" else args.generate
        print(generate_key_for_hwid(h))
    if args.validate:
        ok, r = validate_key(args.validate)
        print(f"valid={ok} reason={r}")
    if args.check:
        info = get_license_info()
        print(json.dumps(info, indent=2))
    if not any([args.hwid, args.generate is not None, args.validate, args.check]):
        p.print_help()
        print(f"\nHWID actuel: {get_hwid()}")
        print(f"Clé générée: {generate_key_for_current_machine()}")
