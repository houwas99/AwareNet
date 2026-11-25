# modules/boost.py — Platoboost integration for AwareNet (obfuscated)
import platform
import subprocess
from requests import session
from datetime import datetime
from hashlib import sha256, md5
import base64 as _b64

# ── Obfuscation helpers ──────────────────────────────────────────────────
# Clé de déobfuscation construite dynamiquement pour éviter strings plain
def _k():
    # Xy9#kP2$vL8qZ!7A  mais assemblé
    return "".join([chr(c) for c in [88,121,57,35,107,80,50,36,118,76,56,113,90,33,55,65]])

def _dx(e):
    k = _k().encode()
    x = _b64.b64decode(e.encode())
    b = bytes([x[i] ^ k[i % len(k)] for i in range(len(x))])
    return b[::-1].decode()

# Service et secret obfusqués (ne pas laisser en clair dans le binaire)
# service 30939 -> xor 0xA5A5 = 0xDD7E
def _svc():
    return 0xDD7E ^ 0xA5A5

# secret obfusqué (Platoboost)
_sec_parts = ["bh1aRV9kAh1OfQxD", "d0MFdzlUDhsJZB8SE3wAXGsQVCJvSlhH"]
def _sec():
    return _dx("".join(_sec_parts))

# Compatibilité anciens noms
service = _svc()
secret = _sec()

use_nonce = True


class Boost:
    def __init__(self, callback=None):
        self.session = session()
        self.session.headers.update({"User-Agent": "Platoboost Python Client/1.0"})
        self.session.headers.update({"Content-Type": "application/json"})
        self.session.headers.update({"Accept": "application/json"})
        self.callback = callback
        
        self.hostname = "https://api.platoboost.com"

        try:
            response = self.session.get(self.hostname + "/public/connectivity", timeout=5)
            if response.status_code != 200 or not (response.json().get("success") == True):
                raise Exception("main domain is offline, falling back..")
        except Exception:
            self.hostname = "https://api.platoboost.net"
        
        self._identifier = self._gethwid()
        self._cached_link = None
        self._cached_time = None
        try:
            self._cache_link()
        except Exception:
            pass

    def _gethwid(self):
        if platform.system() == "Windows":
            try:
                command = "wmic csproduct get uuid"
                uuid = subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL).decode().split("\n")[1].strip()
                if not uuid or uuid.lower() == "uuid":
                    raise ValueError("empty uuid")
            except Exception:
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                        uuid, _ = winreg.QueryValueEx(k, "MachineGuid")
                except Exception:
                    uuid = platform.node() + platform.processor()
        elif platform.system() == "Linux":
            try:
                uuid = subprocess.check_output("cat /etc/machine-id", shell=True, stderr=subprocess.DEVNULL).decode().strip()
            except Exception:
                uuid = platform.node()
        elif platform.system() == "Darwin":
            try:
                uuid = subprocess.check_output(
                    "ioreg -rd1 -c IOPlatformExpertDevice | grep IOPlatformSerialNumber",
                    shell=True, stderr=subprocess.DEVNULL
                ).decode().split('=')[1].strip().replace('"', '')
            except Exception:
                uuid = platform.node()
        else:
            raise OSError("Unsupported operating system")
        
        return sha256(uuid.encode()).hexdigest()

    def _cache_link(self):
        if self._cached_link is None or self._cached_time is None or (datetime.now() - self._cached_time).total_seconds() > 5*60:
            try:
                response = self.session.post(self.hostname + "/public/start", json={
                    "service": _svc(),
                    "identifier": self._identifier,
                }, timeout=10)
            except Exception as e:
                if self.callback is not None:
                    self.callback(f"failed to cache link: {e}")
                return False
            
            if response.status_code == 200:
                try:
                    decoded = response.json()
                except Exception:
                    return False
                
                if decoded.get("success") == True:
                    self._cached_link = decoded["data"]["url"]
                    self._cached_time = datetime.now()
                    return self._cached_link
                else:
                    if self.callback is not None:
                        self.callback(decoded.get("message", "failed to cache link"))
                    return False
            elif response.status_code == 429:
                if self.callback is not None:
                    self.callback("you are being rate limited, please wait 20 seconds and try again.")
                return False
            else:
                if self.callback is not None:
                    self.callback("failed to cache link.")
                return False
        else:
            return self._cached_link
        
    def _generate_nonce(self):
        if use_nonce:
            return md5(str(datetime.now().timestamp()).encode()).hexdigest()
        else:
            return "empty"
        
    def get_link(self):
        link = self._cache_link()
        if link:
            return self._cached_link
        return self._cached_link
    
    
    def _redeem_key(self, key):
        nonce = self._generate_nonce()
        endpoint = self.hostname + "/public/redeem/" + str(_svc())
        
        body = {
            "identifier": self._identifier,
            "key": key
        }
        
        if use_nonce:
            body["nonce"] = nonce
            
        try:
            response = self.session.post(endpoint, json=body, timeout=10)
        except Exception as e:
            if self.callback is not None:
                self.callback(f"server error: {e}")
            return False
        
        if response.status_code == 200:
            decoded = response.json()
            
            if decoded.get("success") == True:
                valid = decoded["data"]["valid"]
                
                if valid:
                    if use_nonce:
                        if decoded["data"]["hash"] == sha256((str.lower(str(valid)) + "-" + nonce + "-" + _sec()).encode()).hexdigest():
                            return valid
                        else:
                            if self.callback is not None:
                                self.callback("failed to verify integrity.")
                            return False
                    else:
                        return True
                else:
                    if self.callback is not None:
                        self.callback("key is invalid.")
                    return False
            else:
                if "unique constraint violation" in decoded.get("message", ""):
                    if self.callback is not None:
                        self.callback("you already have an active key, please wait for it to expire before redeeming it.")
                else:
                    if self.callback is not None:
                        self.callback(decoded.get("message", ""))
                
                return False
        elif response.status_code == 429:
            if self.callback is not None:
                self.callback("you are being rate limited, please wait 20 seconds and try again.")
            return False
        else:
            if self.callback is not None:
                self.callback("server returned an invalid status code, please try again later.")
            return False
     
    def get_flag(self, name):
        nonce = self._generate_nonce()
        endpoint = self.hostname + "/public/flag/" + str(_svc()) + "?name=" + name
        
        if use_nonce:
            endpoint += "&nonce=" + nonce

        try:
            response = self.session.get(endpoint, timeout=10)
        except Exception:
            return None
        
        if response.status_code == 200:
            decoded = response.json()
            
            if decoded.get("success") == True:
                value = decoded["data"]["value"]
                str_value = type(value) == bool and str.lower(str(value)) or str(value)

                if use_nonce:
                    if decoded["data"]["hash"] == sha256((str_value + "-" + nonce + "-" + _sec()).encode()).hexdigest():
                        return value
                    else:
                        if self.callback is not None:
                            self.callback("failed to verify integrity.")
                        return None
                else:
                    return value
            else:
                if self.callback is not None:
                    self.callback(decoded.get("message", ""))
                return None
        else:
            return None
        
    def verify_key(self, key):
        nonce = self._generate_nonce()
        endpoint = self.hostname + "/public/whitelist/" + str(_svc()) + "?identifier=" + self._identifier + "&key=" + key
        
        if use_nonce:
            endpoint += "&nonce=" + nonce
            
        try:
            response = self.session.get(endpoint, timeout=10)
        except Exception as e:
            if self.callback is not None:
                self.callback(f"server error: {e}")
            return False
        
        if response.status_code == 200:
            decoded = response.json()
            
            if decoded.get("success") == True:
                valid = decoded["data"]["valid"]
                
                if valid:
                    if use_nonce:
                        if decoded["data"]["hash"] == sha256((str.lower(str(valid)) + "-" + nonce + "-" + _sec()).encode()).hexdigest():
                            return valid
                        else:
                            if self.callback is not None:
                                self.callback("failed to verify integrity.")
                            return False
                    else:
                        return True
                else:
                    if str.startswith(key, "KEY_") or str.startswith(key, "FREE_"):
                        return self._redeem_key(key)
                    else:
                        if self.callback is not None:
                            self.callback("key is invalid.")
                        return False
            else:
                if self.callback is not None:
                    self.callback(decoded.get("message", ""))
                return False
        elif response.status_code == 429:
            if self.callback is not None:
                self.callback("you are being rate limited, please wait 20 seconds and try again.")
            return False
        else:
            if self.callback is not None:
                self.callback("server returned an invalid status code, please try again later.")
            return False
