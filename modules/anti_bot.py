import re, time, itertools

_cleanup_counter = itertools.count()

BOT_USER_AGENTS = re.compile(
    r'(bot|crawler|spider|scanner|curl|wget|python-urllib|'
    r'postman|httpie|go-http-client|java|perl|ruby|php|'
    r'libwww|wappalyzer|whatweb|nmap|masscan|zgrab|'
    r'ahrefs|semrush|majestic|rogerbot|exabot|'
    r'archive\.org|wayback|gaisbot|dotbot|'
    r'clsagent|nuclei|gobuster|dirbuster|wfuzz)',
    re.I
)

SUSPICIOUS_HEADERS = [
    "x-forwarded-for", "x-real-ip", "x-requested-with",
    "x-forwarded-proto", "x-forwarded-host",
]

BOT_UA_PATTERNS = [
    "headless", "phantom", "selenium", "puppeteer", "playwright",
    "chromium-headless", "chrome-headless",
]

def is_bot(request):
    ua = (request.headers.get("User-Agent", "") or "")
    if BOT_USER_AGENTS.search(ua):
        return True, "bot_user_agent"
    for pattern in BOT_UA_PATTERNS:
        if pattern.lower() in ua.lower():
            return True, f"headless_detected_{pattern}"
    accept = (request.headers.get("Accept", "") or "")
    if not accept or "*/*" in accept:
        pass
    if not ua:
        return True, "no_user_agent"
    return False, ""

def check_rate_limit(ip, cache, limit=10, window=10):
    now = time.time()
    if ip not in cache:
        cache[ip] = []
    cache[ip] = [t for t in cache[ip] if now - t < window]
    if len(cache[ip]) >= limit:
        return True
    cache[ip].append(now)
    if next(_cleanup_counter) % 100 == 0:
        stale = [k for k, v in list(cache.items()) if not v or (now - v[-1]) > window * 2]
        for k in stale:
            del cache[k]
    return False
