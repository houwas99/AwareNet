#!/usr/bin/env python3
"""
tools/generate_key.py — Générateur de clés AwareNet pour l'admin
Usage:
  python tools/generate_key.py                          # clé pour cette machine
  python tools/generate_key.py --hwid ABCD1234EFGH5678  # clé pour un client
  python tools/generate_key.py --hwid HWID --secret "mon_secret"
  python tools/generate_key.py --batch hwids.txt        # génère pour une liste
HWID du client: il le voit dans la fenêtre d'activation ou via /api/license/hwid
"""
import os
import sys
import argparse

# Permet d'importer modules.license depuis la racine
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from modules.license import get_hwid, generate_key_for_hwid, generate_key_for_current_machine, validate_key

def main():
    p = argparse.ArgumentParser(description="Générateur de clés AwareNet")
    p.add_argument("--hwid", help="HWID du client (16 hex). Si vide = HWID local")
    p.add_argument("--secret", help="Secret HMAC (sinon AWARNET_LICENSE_SECRET ou défaut)")
    p.add_argument("--batch", help="Fichier avec 1 HWID par ligne")
    p.add_argument("--validate", help="Valide une clé au lieu de générer")
    p.add_argument("--url", help="Affiche le lien externe configuré")
    args = p.parse_args()

    if args.validate:
        ok, reason = validate_key(args.validate)
        print(f"Cle: {args.validate}")
        print(f"Valide: {ok}  ({reason})")
        if ok:
            print("[OK] Cle OK")
        else:
            print("[X] Cle invalide")
        sys.exit(0 if ok else 1)

    if args.url or os.environ.get("AWARNET_KEY_URL"):
        from modules.license import KEY_URL
        print(f"KEY_URL: {KEY_URL}")

    secret = args.secret or os.environ.get("AWARNET_LICENSE_SECRET") or None
    if secret:
        # override temporaire pour génération
        os.environ["AWARNET_LICENSE_SECRET"] = secret
        # reimport pour prendre en compte le nouveau secret (hack)
        import modules.license as lic
        lic.LICENSE_SECRET = secret

    if args.batch:
        if not os.path.exists(args.batch):
            print(f"Fichier introuvable: {args.batch}", file=sys.stderr)
            sys.exit(1)
        with open(args.batch, "r", encoding="utf-8") as f:
            for line in f:
                hwid = line.strip().upper()
                if not hwid or hwid.startswith("#"):
                    continue
                key = generate_key_for_hwid(hwid)
                print(f"{hwid} -> {key}")
        return

    if args.hwid:
        hwid = args.hwid.strip().upper()
        key = generate_key_for_hwid(hwid)
        print(f"HWID: {hwid}")
        print(f"Cle : {key}")
        ok, _ = validate_key(key, hwid=hwid)
        print(f"Verif: {'OK' if ok else 'ECHEC'}")
    else:
        hwid = get_hwid()
        key = generate_key_for_current_machine()
        print(f"HWID (local): {hwid}")
        print(f"Cle (local) : {key}")
        print(f"\nPour un client, demande son HWID puis:")
        print(f"  python tools/generate_key.py --hwid <HWID_CLIENT>")

if __name__ == "__main__":
    main()
