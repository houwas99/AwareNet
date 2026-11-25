#!/usr/bin/env python3
"""
tools/license_server_example.py — Exemple minimal de serveur de validation online
Héberge ce script sur ton VPS / Render / Railway / Vercel et pointe AWARNET_LICENSE_SERVER vers son URL.

Le .exe appellera:  GET https://ton-serveur.com/validate?key=AWARE-XXXX-...&hwid=ABCD1234...

Ce script répond {"valid": true} si la clé est dans la whitelist ou dérivée du HWID.

Déploie-le et set:
  AWARNET_LICENSE_SERVER=https://ton-serveur.com/validate
  AWARNET_KEY_URL=https://ton-serveur.com/get-key  (page où l'utilisateur récupère sa clé)

Tu peux remplacer la logique par Stripe/Gumroad/Sellix webhook, DB, etc.
"""
from flask import Flask, request, jsonify, render_template_string
import os, hmac, hashlib, re

app = Flask(__name__)

SECRET = os.environ.get("AWARNET_LICENSE_SECRET", "AwareNet-2026-ChangeMe-SuperSecret-!42")
# Optionnel: fichier avec clés pré-générées (1 par ligne)
WHITELIST_FILE = os.environ.get("WHITELIST_FILE", "whitelist.txt")

def hwid_to_key(hwid: str) -> str:
    hm = hmac.new(SECRET.encode(), hwid.strip().upper().encode(), hashlib.sha256).hexdigest().upper()
    core = hm[:16]
    groups = [core[i:i+4] for i in range(0, 16, 4)]
    return "AWARE-" + "-".join(groups)

def load_whitelist():
    if not os.path.exists(WHITELIST_FILE):
        return set()
    with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
        return set(line.strip().upper() for line in f if line.strip() and not line.startswith("#"))

@app.route("/validate")
def validate():
    key = (request.args.get("key") or "").strip().upper()
    hwid = (request.args.get("hwid") or "").strip().upper()
    if not key or not hwid:
        return jsonify({"valid": False, "reason": "missing key or hwid"}), 400
    # 1. whitelist
    wl = load_whitelist()
    if key in wl:
        return jsonify({"valid": True, "reason": "whitelist"})
    # 2. HMAC HWID
    expected = hwid_to_key(hwid)
    if hmac.compare_digest(key, expected):
        return jsonify({"valid": True, "reason": "hwid_match"})
    # 3. invalide
    return jsonify({"valid": False, "reason": "invalid"}), 403

# Page simple pour générer une clé côté client (à protéger par paiement !)
PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>Get AwareNet Key</title>
<style>body{font-family:monospace;max-width:600px;margin:40px auto;padding:20px;background:#080810;color:#e0e0f0}
input{width:100%;padding:10px;background:#12121e;color:white;border:1px solid #333;border-radius:8px;margin:8px 0}
button{width:100%;padding:12px;background:white;color:#080810;border:none;border-radius:8px;font-weight:bold;cursor:pointer}
.box{background:#12121e;padding:16px;border-radius:12px;border:1px solid #222;margin:16px 0}
code{background:#0d0d18;padding:2px 6px;border-radius:4px}
</style></head><body>
<h1>🔑 AwareNet — Obtenir ma clé</h1>
<div class="box">
  <p>Colle ton <b>HWID</b> (affiché dans l'app) :</p>
  <input id="hwid" placeholder="Ex: A1B2C3D4E5F60718" maxlength="16">
  <button onclick="gen()">Générer ma clé</button>
  <p id="out" style="margin-top:12px"></p>
</div>
<p><small>⚠️ Protège cette page par un paiement (Stripe/Gumroad) en prod. Démo libre ici.</small></p>
<script>
async function gen(){
  const hwid=document.getElementById('hwid').value.trim().toUpperCase();
  if(!hwid || hwid.length!==16){ alert('HWID = 16 caractères hex'); return; }
  const r=await fetch('/generate?hwid='+encodeURIComponent(hwid));
  const j=await r.json();
  document.getElementById('out').innerHTML = j.key ? '<b>Ta clé:</b><br><code style="font-size:1.2em">'+j.key+'</code><br><br>Copie-la et colle-la dans AwareNet.' : 'Erreur: '+j.error;
}
</script>
</body></html>
"""

@app.route("/get-key")
def get_key_page():
    return render_template_string(PAGE)

@app.route("/generate")
def generate():
    hwid = (request.args.get("hwid") or "").strip().upper()
    if not re.match(r"^[A-F0-9]{16}$", hwid):
        return jsonify({"error": "invalid hwid, need 16 hex"}), 400
    # En prod: vérifie que l'utilisateur a payé (session Stripe, token, etc.) avant de générer
    key = hwid_to_key(hwid)
    return jsonify({"hwid": hwid, "key": key})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"License server on :{port}  SECRET={SECRET[:6]}***")
    print(f"  Validate: /validate?key=AWARE-...&hwid=ABCD1234EFGH5678")
    print(f"  Get key : /get-key")
    app.run(host="0.0.0.0", port=port, debug=True)
