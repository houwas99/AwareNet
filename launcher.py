#!/usr/bin/env python3
# launcher.py — GUI d'activation AwareNet pour le .exe
# Affiche une fenêtre Tkinter AVANT de lancer Flask si pas de licence.
# Usage normal (dev):  python launcher.py
# Dans l'exe PyInstaller: l'exe lance ce fichier en premier.
import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

# Assure que le dossier du script est dans sys.path
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    from modules.license import get_hwid, validate_key, save_key, is_licensed, is_expired, get_license_info, get_platoboost_link, KEY_URL
except Exception as e:
    print(f"[launcher] license module missing: {e}")
    sys.exit(1)

def _get_hwid_display():
    # Si Platoboost actif, affiche son identifier (64 hex) qui est lié au lien
    try:
        from modules.license import USE_PLATOBOOST, _get_boost
        if USE_PLATOBOOST:
            b = _get_boost()
            if b and hasattr(b, '_identifier'):
                return b._identifier
    except Exception:
        pass
    return get_hwid()

HWID = _get_hwid_display()
def _get_key_url():
    try:
        return get_platoboost_link()
    except Exception:
        return KEY_URL
KEY_URL_DYNAMIC = _get_key_url()
# Detecte Platoboost actif
try:
    from modules.license import USE_PLATOBOOST as _USE_PB
    IS_PLATOBOOST = bool(_USE_PB)
except Exception:
    IS_PLATOBOOST = False

def start_server():
    """Lance Flask dans un thread séparé puis ouvre le navigateur."""
    import time
    # import différé pour éviter Tkinter + Flask conflit
    try:
        from app import app, socketio, ATTACKER_URL_TOKEN, ATTACKER_PASSWORD
    except Exception as e:
        messagebox.showerror("Erreur", f"Impossible de charger app.py:\n{e}")
        return

    def run():
        try:
            # Charge ce que app.py fait normalement au boot
            from modules.database import get_db
            from modules.email_sender import email_sender
            from modules.sms_sender import sms_sender
            try:
                from app import load_custom_templates, load_campaigns, auto_delete
                load_custom_templates()
                load_campaigns()
            except Exception:
                pass
            try:
                import threading as th
                th.Thread(target=auto_delete, daemon=True).start()
            except Exception:
                pass
            socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True, use_reloader=False)
        except Exception as e:
            print(f"[server] error: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(1.2)
    url = f"http://127.0.0.1:5000/panel/{ATTACKER_URL_TOKEN}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    # Optionnel: afficher l'URL
    try:
        messagebox.showinfo("AwareNet", f"Serveur démarré !\n\nPanel: {url}\nPassword: {ATTACKER_PASSWORD}\n\nLe navigateur va s'ouvrir.")
    except Exception:
        pass

class LicenseGUI:
    def __init__(self, root):
        self.root = root
        root.title("AwareNet — Activation")
        root.geometry("540x680")
        root.minsize(520, 620)
        root.resizable(True, True)
        root.configure(bg="#080810")
        # Centrer
        try:
            root.eval('tk::PlaceWindow . center')
        except Exception:
            pass

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Icône
        header = tk.Frame(root, bg="#12121e", height=90)
        header.pack(fill="x")
        tk.Label(header, text="🔑", font=("Segoe UI", 28), bg="#12121e", fg="white").pack(pady=(18, 2))
        tk.Label(header, text="AwareNet — Activation requise", font=("Segoe UI", 12, "bold"), bg="#12121e", fg="white").pack()
        tk.Label(header, text="Version .EXE — Licence liée à ta machine", font=("Consolas", 8), bg="#12121e", fg="#5a5a7a").pack(pady=(2, 10))

        body = tk.Frame(root, bg="#080810")
        body.pack(fill="both", expand=True, padx=22, pady=16)

        # HWID - Platoboost: lien déjà lié, pas besoin de coller HWID
        if IS_PLATOBOOST:
            tk.Label(body, text="ID machine (auto-lié, pas à coller) :", font=("Consolas", 8, "bold"), bg="#080810", fg="#5a5a7a").pack(anchor="w")
            # HWID Platoboost = 64 hex, affiche tronqué
            hwid_short = HWID[:16] + "..." + HWID[-8:] if len(HWID) > 32 else HWID
            hwid_frame = tk.Frame(body, bg="#0d0d18", highlightbackground="#2e2e48", highlightthickness=1)
            hwid_frame.pack(fill="x", pady=(4, 6))
            tk.Label(hwid_frame, text=hwid_short, font=("Consolas", 8, "bold"), bg="#0d0d18", fg="white").pack(side="left", padx=10, pady=8)
            tk.Button(hwid_frame, text="Copier", font=("Consolas", 8), bg="#1a1a2e", fg="white", relief="flat", padx=10, pady=2, command=self.copy_hwid).pack(side="right", padx=8)
            tk.Label(body, text="1. Clique 'Obtenir ma clé' → complète Linkvertise\n2. Copie ta clé KEY_...\n3. Colle-la ci-dessous et clique Activer", font=("Consolas", 7), bg="#080810", fg="#5a5a7a", justify="left").pack(anchor="w", pady=(4, 10))
        else:
            tk.Label(body, text="HWID (ID machine) :", font=("Consolas", 8, "bold"), bg="#080810", fg="#5a5a7a").pack(anchor="w")
            hwid_frame = tk.Frame(body, bg="#0d0d18", highlightbackground="#2e2e48", highlightthickness=1)
            hwid_frame.pack(fill="x", pady=(4, 6))
            tk.Label(hwid_frame, text=HWID, font=("Consolas", 10, "bold"), bg="#0d0d18", fg="white").pack(side="left", padx=10, pady=8)
            tk.Button(hwid_frame, text="Copier", font=("Consolas", 8), bg="#1a1a2e", fg="white", relief="flat", padx=10, pady=2, command=self.copy_hwid).pack(side="right", padx=8)
            tk.Label(body, text="1. Clique 'Obtenir ma clé' → colle ton HWID sur le site\n2. Récupère ta clé AWARE-XXXX-XXXX-XXXX-XXXX\n3. Colle-la ci-dessous et clique Activer", font=("Consolas", 7), bg="#080810", fg="#5a5a7a", justify="left").pack(anchor="w", pady=(4, 10))

        # Bouton lien externe
        self.link_btn = tk.Button(body, text="🔗  Obtenir ma clé — Lien externe ↗", font=("Segoe UI", 9, "bold"), bg="#1e1e32", fg="white", relief="flat", padx=12, pady=10, command=self.open_key_url, cursor="hand2", activebackground="#2a2a44")
        self.link_btn.pack(fill="x", pady=(0, 12))

        tk.Label(body, text="Clé de licence :", font=("Consolas", 8, "bold"), bg="#080810", fg="#5a5a7a").pack(anchor="w")
        self.key_var = tk.StringVar()
        placeholder = "KEY_..." if IS_PLATOBOOST else "AWARE-XXXX-XXXX-XXXX-XXXX"
        self.entry = tk.Entry(body, textvariable=self.key_var, font=("Consolas", 11), bg="#0d0d18", fg="white", insertbackground="white", relief="flat", highlightbackground="#2e2e48", highlightthickness=1)
        self.entry.pack(fill="x", pady=(4, 12), ipady=6)
        # placeholder via insert
        self.entry.insert(0, "")
        self.entry.config(fg="white")
        # bind seulement si pas Platoboost (sinon on garde KEY_ tel quel)
        if not IS_PLATOBOOST:
            self.entry.bind("<KeyRelease>", self.on_key_type)
        self.entry.focus_set()
        if IS_PLATOBOOST:
            # hint
            tk.Label(body, text="Colle la clé KEY_... copiée après Linkvertise", font=("Consolas", 7), bg="#080810", fg="#5a5a7a").pack(anchor="w", pady=(0,6))

        self.activate_btn = tk.Button(body, text="Activer AwareNet  →", font=("Segoe UI", 10, "bold"), bg="white", fg="#080810", relief="flat", padx=12, pady=10, command=self.activate, activebackground="#e0e0f0", cursor="hand2")
        self.activate_btn.pack(fill="x")

        self.status = tk.Label(body, text=f"Lien configuré : {KEY_URL_DYNAMIC}", font=("Consolas", 7), bg="#080810", fg="#2e2e48", wraplength=430, justify="center")
        self.status.pack(pady=(10, 0))

        # Support Entrée pour activer
        root.bind("<Return>", lambda e: self.activate())
        # Vérifie connexion internet pour Platoboost
        is_offline = False
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=2).close()
        except Exception:
            is_offline = True
        info = get_license_info()
        # Hors connexion : affiche message
        if is_offline:
            self.status.config(text="📡 Hors connexion — internet requis pour Platoboost", fg="#e8294c")
            tk.Label(body, text="Hors connexion — vérifiez votre internet", font=("Consolas", 7, "bold"), bg="#080810", fg="#e8294c").pack(pady=(6,0))
        elif is_licensed():
            exp = info.get("expires_at") or "?"
            rem = info.get("remaining_hours") or 0
            self.status.config(text=f"✓ Activé — expire {exp} ({rem}h restantes)", fg="#1ed760")
            self.activate_btn.config(text="Lancer AwareNet  →", bg="#1ed760", fg="white", activebackground="#1aa84d")
            tk.Label(body, text=f"⏳ Licence 24h — expire: {exp}", font=("Consolas", 7), bg="#080810", fg="#1ed760").pack(pady=(6,0))
        elif info.get("expired"):
            self.status.config(text=f"⏰ Expirée après {info.get('duration_hours',24)}h — récupère une nouvelle clé", fg="#e8294c")
            self.activate_btn.config(text="Réactiver (nouvelle clé) →", bg="#e8294c", fg="white", activebackground="#b91c3a")
            tk.Label(body, text="Ta clé a expiré. Récupère nouvelle KEY_...", font=("Consolas", 7), bg="#080810", fg="#e8294c").pack(pady=(6,0))
            header.config(bg="#1a0a0f")
        elif info.get("reason") and "hors_connexion" in str(info.get("reason")):
            self.status.config(text="📡 Hors connexion — internet requis", fg="#e8294c")
            tk.Label(body, text="Hors connexion — vérifiez votre internet", font=("Consolas", 7), bg="#080810", fg="#e8294c").pack(pady=(6,0))
        else:
            tk.Label(body, text="Clé Platoboost valable 24h — Linkvertise requis", font=("Consolas", 7), bg="#080810", fg="#5a5a7a").pack(pady=(6,0))

    def copy_hwid(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(HWID)
            self.root.update()
            self.status.config(text="✓ HWID copié !", fg="#1ed760")
            self.root.after(1500, lambda: self.status.config(text=f"Lien configuré : {KEY_URL_DYNAMIC}", fg="#2e2e48"))
        except Exception:
            pass

    def open_key_url(self):
        try:
            url = _get_key_url()
            webbrowser.open(url)
            self.status.config(text="Navigateur ouvert → récupère ta clé Platoboost", fg="#e0e0f0")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le lien:\n{KEY_URL_DYNAMIC}\n\n{e}")

    def on_key_type(self, event=None):
        if IS_PLATOBOOST:
            return  # Platoboost: ne pas reformater KEY_...
        # Auto format AWARE-XXXX-XXXX-XXXX-XXXX
        v = self.key_var.get().upper().replace(" ", "").replace("_", "-")
        raw = re_clean(v)
        if raw.startswith("AWARE"):
            raw = raw[5:]
        raw = raw[:16]
        if raw:
            groups = [raw[i:i+4] for i in range(0, len(raw), 4)]
            formatted = "AWARE-" + "-".join(groups)
            if formatted != v:
                pos = self.entry.index(tk.INSERT)
                self.key_var.set(formatted)
                try:
                    self.entry.icursor(pos + (len(formatted)-len(v)))
                except Exception:
                    pass
        else:
            if v and not v.startswith("A"):
                self.key_var.set("")

    def activate(self):
        key = self.key_var.get().strip()
        if IS_PLATOBOOST:
            key = key.strip()  # garde KEY_ tel quel (sensitive)
        else:
            key = key.strip().upper()
        if not key:
            msg = "Colle ta clé KEY_... (Platoboost)" if IS_PLATOBOOST else "Colle ta clé AWARE-XXXX-XXXX-XXXX-XXXX"
            messagebox.showwarning("Clé manquante", msg)
            return
        ok, reason = validate_key(key)
        if ok:
            try:
                save_key(key)
                info = get_license_info()
            except Exception as e:
                messagebox.showerror("Erreur", f"Clé valide mais sauvegarde échouée:\n{e}")
                return
            messagebox.showinfo("Activé ✓", f"AwareNet est activé pour 24h !\nHWID: {HWID}\nClé: {key[:11]}***\nExpire: {info.get('expires_at')}")
            self.root.destroy()
            start_server()
            # garde le process vivant (le thread Flask tourne en daemon, on doit bloquer)
            # On ne quitte pas, on laisse tkinter mainloop remplacé par un simple sleep
            try:
                import time
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
        else:
            if "hors_connexion" in reason:
                msg = f"Hors connexion — vérifiez votre internet.\n\nPlatoboost nécessite une connexion pour valider la clé.\nHWID: {HWID}"
            elif reason == "invalid":
                msg = f"Clé invalide pour ce HWID.\n\nHWID: {HWID}\nClé: {key}\n\nVérifie que tu as bien passé le Linkvertise."
            elif "server_error" in reason:
                msg = f"Serveur injoignable:\n{reason}\n\nVérifie ta connexion."
            else:
                msg = f"Clé invalide ({reason})\nHWID: {HWID}"
            messagebox.showerror("Hors connexion" if "hors_connexion" in reason else "Clé invalide", msg)
            self.status.config(text=f"✗ {msg.splitlines()[0]}", fg="#e8294c")

def re_clean(s: str) -> str:
    # garde AWARE + hex
    out = ""
    for c in s:
        if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-":
            out += c
    # enlève tirets pour retraitement
    out = out.replace("-", "")
    return out

def main():
    # Si déjà licencié et non expiré, lancer direct sans GUI
    from modules.license import is_expired
    if is_licensed() and not is_expired() and "--gui" not in sys.argv and os.environ.get("AWARNET_ALWAYS_GUI") != "1":
        info = get_license_info()
        print(f"[launcher] Licence OK ({HWID}) — expire {info.get('expires_at')} — démarrage direct")
        start_server()
        # bloque
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sys.exit(0)
        return
    if is_expired():
        print(f"[launcher] Licence expirée — ouverture GUI renouvellement")

    root = tk.Tk()
    # Icône fenêtre + barre des tâches (fonctionne en source et en .exe frozen)
    try:
        import sys as _sys_icon
        _icon_candidates = []
        if getattr(_sys_icon, 'frozen', False) and hasattr(_sys_icon, '_MEIPASS'):
            _icon_candidates.append(os.path.join(_sys_icon._MEIPASS, "icon.ico"))
        _icon_candidates.append(os.path.join(BASE, "icon.ico"))
        # si exe déplacé sur Bureau, BASE = dossier parent de l'exe, icon.ico doit être à côté ou embarqué
        # fallback: dossier de l'exécutable
        try:
            _exe_dir = os.path.dirname(os.path.abspath(_sys_icon.executable))
            _icon_candidates.append(os.path.join(_exe_dir, "icon.ico"))
        except Exception:
            pass
        for _ic in _icon_candidates:
            if os.path.exists(_ic):
                try:
                    root.iconbitmap(_ic)
                    break
                except Exception:
                    continue
    except Exception:
        pass
    app_gui = LicenseGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
