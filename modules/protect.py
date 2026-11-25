# modules/protect.py — Protections anti-reverse pour .exe AwareNet
import os
import sys

# ── Bypass protection ────────────────────────────────────────────────────
# En mode .exe (frozen), AWARNET_NO_LICENSE=1 est ignoré sauf si .dev existe
# Cela empêche un utilisateur de bypass facilement avec `set AWARNET_NO_LICENSE=1`

def is_bypass_allowed() -> bool:
    val = os.environ.get("AWARNET_NO_LICENSE", "").strip()
    if val != "1":
        return False
    if not getattr(sys, 'frozen', False):
        return True
    # en exe, exige .dev à côté de l'exe OU dans cwd/base OU env dev key
    try:
        candidates = []
        try:
            candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), ".dev"))
        except Exception:
            pass
        try:
            candidates.append(os.path.join(os.getcwd(), ".dev"))
        except Exception:
            pass
        try:
            # _BASE du projet si dispo
            from modules.license import _BASE as _b
            candidates.append(os.path.join(_b, ".dev"))
        except Exception:
            pass
        for p in candidates:
            if p and os.path.exists(p):
                return True
        if os.environ.get("AWARNET_DEV_KEY") == "AwareNet-Dev-2026":
            return True
    except Exception:
        pass
    return False

# ── Anti-debug (Windows) ─────────────────────────────────────────────────
def is_debugger_present() -> bool:
    try:
        if os.environ.get("PYDEVD_USE_FRAME_EVAL") or os.environ.get("PYTHONBREAKPOINT"):
            return True
        # Windows IsDebuggerPresent
        import ctypes
        try:
            k32 = ctypes.windll.kernel32
            if k32.IsDebuggerPresent():
                return True
            # CheckRemoteDebuggerPresent
            is_dbg = ctypes.c_bool(False)
            k32.CheckRemoteDebuggerPresent(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(is_dbg))
            if is_dbg.value:
                return True
        except Exception:
            pass
        # Vérifie si un debugger Python est attaché (sys.gettrace)
        if sys.gettrace() is not None:
            # en dev c'est normal, en exe frozen c'est suspect
            if getattr(sys, 'frozen', False):
                return True
    except Exception:
        pass
    return False

def anti_debug_check(block: bool = False):
    """Si debugger détecté en exe, on peut bloquer ou juste logger."""
    if is_debugger_present():
        if block and getattr(sys, 'frozen', False):
            # en exe, on quitte si debugger
            try:
                import time
                print("[protect] Debugger detected — exiting")
                time.sleep(1)
            except Exception:
                pass
            sys.exit(1)
        return True
    return False

# ── Intégrité basique ────────────────────────────────────────────────────
# Vérifie que les fichiers critiques n'ont pas été modifiés après build
# On stocke un hash embarqué au build (optionnel)

def verify_integrity() -> bool:
    # Pour l'instant, on vérifie juste que les modules existent
    # Tu peux étendre avec un hash embarqué
    try:
        import modules.license, modules.boost
        # vérifie que les secrets déobfusqués sont cohérents
        from modules.license import _LIC_OBF, _lic_deobf
        from modules.boost import _sec
        if _lic_deobf(_LIC_OBF) != "AwareNet-2026-ChangeMe-SuperSecret-!42":
            return False
        if _sec() != "da37cc11-80e6-4b87-a62b-24189044fcd6":
            return False
    except Exception:
        return False
    return True

# ── VM / Sandbox détection légère ────────────────────────────────────────
def is_sandbox() -> bool:
    try:
        import platform
        # Check for common sandbox artefacts
        suspicious = ["sandbox", "vmware", "virtualbox", "qemu", "vbox"]
        node = platform.node().lower()
        for s in suspicious:
            if s in node:
                return True
        # Check RAM < 2GB (common sandbox)
        try:
            import psutil
            if psutil.virtual_memory().total < 2 * 1024**3:
                # pas bloquant, juste info
                pass
        except Exception:
            pass
    except Exception:
        pass
    return False
