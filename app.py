#!/usr/bin/env python3
# DeathRow Scraper – Flask UI with smart 403 recovery, TLS impersonation, and Playwright fallback (auto)

import csv
import io
import re
import time
import random
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, redirect, url_for
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

app = Flask(__name__)

HTML_TMPL = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>DeathRow Web Scraper</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:2rem;background:#0b0d10;color:#eaeef3}
  h1{font-size:1.6rem;margin:0 0 1rem}
  form{display:grid;gap:0.75rem;max-width:1100px}
  input,textarea,button{padding:0.7rem;border-radius:8px;border:1px solid #2a2f36;background:#12151b;color:#eaeef3}
  textarea{min-height:70px}
  input:focus,textarea:focus{outline:1px solid #3a7bfd}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;align-items:end}
  .card{background:#0f1217;border:1px solid #1b212a;border-radius:12px;padding:1rem;margin-top:1rem}
  a{color:#8ab4ff;word-break:break-all}
  code,pre{background:#0f1217;border:1px solid #1b212a;border-radius:8px;padding:0.35rem;display:block;overflow:auto}
  .muted{color:#aab3c2}
  .btn{cursor:pointer;background:#1a73e8;border:none}
  .row{display:flex;gap:0.5rem;flex-wrap:wrap}
  .badge{background:#11161e;border:1px solid #202735;border-radius:999px;padding:0.25rem 0.6rem;font-size:0.8rem}
  .danger{color:#ff6b6b}
  label.inline{display:flex;align-items:center;gap:.5rem}
</style>
</head>
<body>
<center><h1>DeathRow Web Scraper</h1></center>

<form method="POST" action="{{ url_for('scrape') }}">
  <div class="grid">
    <div>
      <label for="url">Webpage URL</label>
      <input id="url" name="url" type="text" placeholder="https://example.com/path" required value="{{ url or '' }}">
    </div>
    <div>
      <label for="selector">Optional CSS Selector (e.g., article p, .price, #content)</label>
      <input id="selector" name="selector" type="text" placeholder="article p" value="{{ selector or '' }}">
    </div>
  </div>
  <div class="grid">
    <div>
      <label for="delay">Polite Delay (seconds)</label>
      <input id="delay" name="delay" type="number" min="0" max="10" step="0.5" value="{{ delay or 1 }}">
    </div>
    <div>
      <label for="user_agent">User-Agent (optional)</label>
      <input id="user_agent" name="user_agent" type="text" placeholder="Paste your exact Chrome UA if needed" value="{{ user_agent or '' }}">
    </div>
  </div>
  <div class="grid">
    <div>
      <label for="referer">Referer (optional)</label>
      <input id="referer" name="referer" type="text" placeholder="https://www.google.com/" value="{{ referer or '' }}">
    </div>
    <div>
      <label for="proxy">HTTP(S) Proxy (optional)</label>
      <input id="proxy" name="proxy" type="text" placeholder="http://user:pass@host:port" value="{{ proxy or '' }}">
    </div>
  </div>
  <div class="grid">
    <div>
      <label for="cookies">Cookies (optional: key=value; key2=value2)</label>
      <textarea id="cookies" name="cookies" placeholder="sessionid=...; __cf_bm=...">{{ cookies or '' }}</textarea>
    </div>
    <div>
      <label class="inline"><input type="checkbox" name="prime_cookies" value="1" {% if prime_cookies %}checked{% endif %}> Prime cookies (hit site root first)</label>
      <label class="inline"><input type="checkbox" name="aggressive" value="1" {% if aggressive %}checked{% endif %}> Aggressive anti-403 mode</label>
      <label class="inline"><input type="checkbox" name="use_browser" value="1" {% if use_browser %}checked{% endif %}> Use headless browser (Playwright) if blocked</label>
      <div class="muted">
        cloudscraper: <span class="badge">{{ 'OK' if cloudscraper_ok else 'missing' }}</span>
        httpx: <span class="badge">{{ 'OK' if httpx_ok else 'missing' }}</span>
        curl_cffi: <span class="badge">{{ 'OK' if curlcffi_ok else 'missing' }}</span>
        playwright: <span class="badge">{{ 'OK' if playwright_ok else 'missing' }}</span>
      </div>
    </div>
  </div>
  <div class="row">
    <button class="btn" type="submit">Scrape</button>
    <a class="badge" href="{{ url_for('home') }}">Reset</a>
  </div>
  <div class="muted">Tip: Paste messy URLs — we’ll auto-fix common issues. For tough 403s, add cookies & enable Aggressive + Browser mode.</div>
</form>

{% if error %}
  <div class="card"><strong class="danger">Error:</strong> {{ error }}</div>
{% endif %}

{% if result %}
  <div class="card">
    <h2>Page Summary</h2>
    <div class="row">
      <span class="badge">URL: {{ result.final_url }}</span>
      <span class="badge">Status: {{ result.status_code }}</span>
      <span class="badge">Content-Type: {{ result.content_type }}</span>
      <span class="badge">Method: {{ result.method_used }}</span>
    </div>
    <p><strong>Title:</strong> {{ result.title or '—' }}</p>
    <p><strong>Meta Description:</strong> {{ result.meta_description or '—' }}</p>
  </div>

  <div class="card">
    <h2>Headings (H1–H3)</h2>
    {% if result.headings %}
      <ul>
      {% for h in result.headings %}
        <li><strong>{{ h.tag }}</strong> — {{ h.text }}</li>
      {% endfor %}
      </ul>
    {% else %}
      <p class="muted">No headings found.</p>
    {% endif %}
  </div>

  <div class="card">
    <h2>Links (same host highlighted)</h2>
    {% if result.links %}
      <div class="row">
        <a class="badge" href="{{ url_for('download_links') }}">Download Links CSV</a>
      </div>
      <ul>
      {% for link in result.links %}
        <li>
          <a href="{{ link.href }}" target="_blank" rel="noopener">{{ link.text or link.href }}</a>
          {% if link.same_host %}<span class="badge">same host</span>{% endif %}
        </li>
      {% endfor %}
      </ul>
    {% else %}
      <p class="muted">No links found.</p>
    {% endif %}
  </div>

  <div class="card">
    <h2>Images</h2>
    {% if result.images %}
      <ul>
      {% for img in result.images %}
        <li><a href="{{ img.src }}" target="_blank" rel="noopener">{{ img.alt or img.src }}</a></li>
      {% endfor %}
      </ul>
    {% else %}
      <p class="muted">No images found.</p>
    {% endif %}
  </div>

  {% if result.selector and result.selector_matches is not none %}
  <div class="card">
    <h2>Selector: <code>{{ result.selector }}</code></h2>
    {% if result.selector_matches %}
      <p><strong>{{ result.selector_matches|length }}</strong> match(es)</p>
      <ul>
      {% for m in result.selector_matches[:100] %}
        <li><code>{{ m }}</code></li>
      {% endfor %}
      </ul>
      {% if result.selector_matches|length > 100 %}
        <p class="muted">Showing first 100 matches…</p>
      {% endif %}
    {% else %}
      <p class="muted">No matches for this selector.</p>
    {% endif %}
  </div>
  {% endif %}
{% endif %}
</body>
</html>
"""

_LAST_LINKS = []

BROWSER_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]
SMART_REFERERS = ["", "{origin}", "https://www.google.com/", "https://www.bing.com/"]
SMART_UAS = BROWSER_UAS + [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ----- optional fallbacks availability -----
CLOUDSCRAPER_OK = False
HTTPX_OK = False
CURLCFFI_OK = False
PLAYWRIGHT_OK = False
try:
    import cloudscraper
    CLOUDSCRAPER_OK = True
except Exception:
    pass
try:
    import httpx
    HTTPX_OK = True
except Exception:
    pass
try:
    from curl_cffi import requests as curlreq
    CURLCFFI_OK = True
except Exception:
    pass
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except Exception:
    pass

# ---------------- URL helpers ----------------
def normalize_url(u: str) -> str:
    """Fix common input mistakes; assume https if no scheme. (safe char classes—no bad ranges)"""
    if not u:
        return u
    u = u.strip().replace("\\", "/")
    u = re.sub(r'^(https?):/([^/])', r'\1://\2', u, flags=re.IGNORECASE)  # http:/ -> http://
    u = re.sub(r'^(https?):///*', r'\1://', u, flags=re.IGNORECASE)        # collapse extra slashes
    u = re.sub(r'^(https?)(//)', r'\1://', u, flags=re.IGNORECASE)         # https// -> https://
    u = re.sub(r'^wwwhttps?://', 'https://', u, flags=re.IGNORECASE)       # wwwhttps:// -> https://
    if re.match(r'^www\.', u, flags=re.IGNORECASE):
        u = 'https://' + u
    if not re.match(r'^[A-Za-z][A-Za-z0-9+\.\-]*://', u):
        u = 'https://' + u
    u = re.sub(r'^(https?://)/*', r'\1', u, flags=re.IGNORECASE)
    return u

def is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

# ---------------- block detector ----------------
def _looks_blocked(resp_text: str, status: int) -> bool:
    # treat these as blocked immediately
    if status in (401, 403, 429):
        return True

    low = (resp_text or "").lower()

    blocked_markers = [
        "access denied", "request blocked", "forbidden", "unusual traffic",
        "cloudflare", "attention required", "robot check", "/captcha",
        "akamai", "perimeterx", "datadome", "sucuri", "verification required",
        "are you a human", "temporary block", "blocked by", "ddos protection",
    ]
    if any(m in low for m in blocked_markers):
        return True

    # Only consider small-body==blocked when it's actually an error-ish status
    if len(low.strip()) < 400 and (400 <= status < 600):
        return True

    return False

# ---------------- networking ----------------
def make_session(proxy: str | None = None):
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s

def _make_headers(ua: str, referer: str, site_hint: str = "none", extra_cookies: dict | None = None) -> dict:
    ua = (ua.strip() or random.choice(SMART_UAS))
    h = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Safer if brotli isn't installed:
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": '"Chromium";v="127", "Not=A?Brand";v="24", "Google Chrome";v="127"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Site": site_hint,
    }
    if referer:
        h["Referer"] = referer
    if extra_cookies:
        cookie_str = "; ".join([f"{k}={v}" for k, v in extra_cookies.items() if k and v])
        if cookie_str:
            h["Cookie"] = cookie_str
    return h

def _parse_cookies(raw: str) -> dict:
    jar = {}
    for part in (raw or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                jar[k] = v
    return jar

def polite_get(url: str, user_agent: str = "", delay: float = 1.0, timeout: int = 20,
               referer: str = "", prime_cookies: bool = False, proxy: str | None = None,
               cookies_raw: str = "", aggressive: bool = False):
    time.sleep(max(0.0, delay))
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    session = make_session(proxy)

    cookies_kv = _parse_cookies(cookies_raw)

    if prime_cookies:
        try:
            session.get(
                origin,
                headers=_make_headers(user_agent or random.choice(SMART_UAS), origin, "same-origin", cookies_kv),
                timeout=timeout, allow_redirects=True
            )
            time.sleep(0.3)
        except requests.RequestException:
            pass

    site_hint = "same-origin" if (referer and urlparse(referer).netloc == parsed.netloc) else ("cross-site" if referer else "none")
    base_headers = _make_headers(user_agent or random.choice(SMART_UAS), referer or origin, site_hint, cookies_kv)
    resp = session.get(url, headers=base_headers, timeout=timeout, allow_redirects=True)

    # Rotate/fallback for any of these blocks
    if resp.status_code not in (401, 403, 429):
        return resp

    # Rotate UA+Referer
    for try_ua in random.sample(SMART_UAS, k=min(len(SMART_UAS), 5)):
        for ref in SMART_REFERERS:
            if ref == "{origin}":
                hdrs = _make_headers(try_ua, origin, "same-origin", cookies_kv)
            elif ref:
                hdrs = _make_headers(try_ua, ref, "cross-site", cookies_kv)
            else:
                hdrs = _make_headers(try_ua, "", "none", cookies_kv)
            time.sleep(0.4)
            r = session.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
            if r.status_code not in (401, 403, 429) and r.ok and not _looks_blocked(r.text, r.status_code):
                return r

    if not aggressive:
        return resp

    # Aggressive fallbacks
    if CLOUDSCRAPER_OK:
        try:
            scraper = cloudscraper.create_scraper()
            r2 = scraper.get(url, headers=_make_headers(user_agent, referer or origin, site_hint, cookies_kv),
                             allow_redirects=True, timeout=timeout, proxies=session.proxies or None)
            if 200 <= r2.status_code < 400:
                class ScraperShim:
                    def __init__(self, r): self.status_code, self.headers, self.text, self.url, self.ok = r.status_code, dict(r.headers), r.text, r.url, True
                return ScraperShim(r2)
        except Exception:
            pass

    if HTTPX_OK:
        try:
            headers = _make_headers(user_agent, referer or origin, site_hint, cookies_kv)
            proxies = session.proxies or None
            with httpx.Client(http2=True, headers=headers, follow_redirects=True, timeout=timeout, proxies=proxies) as c:
                r3 = c.get(url)
            if 200 <= r3.status_code < 400:
                class HttpxShim:
                    def __init__(self, r): self.status_code, self.headers, self.text, self.url, self.ok = r.status_code, dict(r.headers), r.text, str(r.url), True
                return HttpxShim(r3)
        except Exception:
            pass

    if CURLCFFI_OK:
        try:
            imp = "chrome127" if "Chrome/127" in (user_agent or "") else ("chrome124" if "Chrome/124" in (user_agent or "") else "chrome127")
            headers = _make_headers(user_agent, referer or origin, site_hint, cookies_kv)
            proxies = {"http": proxy, "https": proxy} if proxy else None
            r5 = curlreq.get(url, headers=headers, impersonate=imp, allow_redirects=True, timeout=timeout, proxies=proxies)
            class CffiShim:
                def __init__(self, r): self.status_code, self.headers, self.text, self.url, self.ok = r.status_code, dict(r.headers), r.text, r.url, 200 <= r.status_code < 400
            if 200 <= r5.status_code < 400:
                return CffiShim(r5)
        except Exception:
            pass

    return resp

# ---------------- Playwright cookie helper ----------------
def _cookie_items_for_playwright(raw_cookie_str: str, url: str):
    """Convert 'k=v; a=b' into Playwright cookie dicts for the URL's domain."""
    if not raw_cookie_str:
        return []
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    jar = []
    for part in raw_cookie_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                jar.append({"name": k, "value": v, "domain": host, "path": "/", "httpOnly": False, "secure": True})
    return jar

# ---------------- Playwright fallback ----------------
def browser_get(url: str, user_agent: str = "", referer: str = "", timeout: int = 75,
                proxy: str | None = None, cookies_raw: str = ""):
    if not PLAYWRIGHT_OK:
        raise RuntimeError("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
    if "#" in url:
        url = url.split("#", 1)[0]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        context_args = {
            "viewport": {"width": 1366, "height": 768},
            "java_script_enabled": True,
            "timezone_id": "Africa/Nairobi",
            "locale": "en-US",
        }
        if proxy:
            context_args["proxy"] = {"server": proxy}
        if user_agent:
            context_args["user_agent"] = user_agent
        context = browser.new_context(**context_args)
        context.add_init_script("""Object.defineProperty(navigator, 'webdriver', {get: () => undefined});""")

        # inject user cookies for this domain
        try:
            cookie_items = _cookie_items_for_playwright(cookies_raw, url)
            if cookie_items:
                context.add_cookies(cookie_items)
        except Exception:
            pass

        page = context.new_page()

        def _route_block(route):
            r = route.request
            if r.resource_type in ("image", "media", "font", "stylesheet"):
                return route.abort()
            return route.continue_()
        page.route("**/*", _route_block)

        if referer:
            page.set_extra_http_headers({"Referer": referer, "Accept-Language": "en-US,en;q=0.9"})

        page.set_default_timeout(timeout * 1000)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        page.wait_for_timeout(800)
        try:
            page.evaluate("() => { window.scrollBy(0, document.body.scrollHeight/2); }")
        except Exception:
            pass
        page.wait_for_timeout(500)

        html = page.content()
        final_url = page.url

        class R:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            text = html
            url = final_url
            ok = True

        context.close()
        browser.close()
        return R()

# ---------------- parsing ----------------
def extract_summary(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    desc_el = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    meta_description = (desc_el.get("content") or "").strip() if desc_el else ""
    headings = []
    for tag in ("h1", "h2", "h3"):
        for el in soup.find_all(tag):
            txt = el.get_text(" ", strip=True)
            if txt:
                headings.append({"tag": tag.upper(), "text": txt})
    links = []
    base_host = urlparse(base_url).netloc
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        text = a.get_text(" ", strip=True)
        same_host = urlparse(href).netloc == base_host
        links.append({"href": href, "text": text, "same_host": same_host})
    images = []
    for img in soup.find_all("img", src=True):
        src = urljoin(base_url, img["src"])
        alt = img.get("alt", "").strip()
        images.append({"src": src, "alt": alt})
    return title, meta_description, headings, links, images

# ---------------- routes ----------------
@app.get("/")
def home():
    return render_template_string(
        HTML_TMPL,
        prime_cookies=False,
        aggressive=False,
        use_browser=False,
        cookies="",
        cloudscraper_ok=CLOUDSCRAPER_OK,
        httpx_ok=HTTPX_OK,
        curlcffi_ok=CURLCFFI_OK,
        playwright_ok=PLAYWRIGHT_OK,
    )

@app.post("/scrape")
def scrape():
    global _LAST_LINKS
    _LAST_LINKS = []

    raw_url = (request.form.get("url") or "").strip()
    selector = (request.form.get("selector") or "").strip()
    delay_raw = (request.form.get("delay") or "1").strip()
    user_agent = (request.form.get("user_agent") or "").strip()
    referer = (request.form.get("referer") or "").strip()
    proxy = (request.form.get("proxy") or "").strip() or None
    cookies_raw = (request.form.get("cookies") or "").strip()
    prime_cookies = request.form.get("prime_cookies") == "1"
    aggressive = request.form.get("aggressive") == "1"
    use_browser = request.form.get("use_browser") == "1"

    url = normalize_url(raw_url)
    if not is_valid_url(url):
        error = f"Please provide a valid URL. You entered: “{raw_url}”."
        return render_template_string(
            HTML_TMPL, error=error, url=raw_url, selector=selector,
            cookies=cookies_raw, user_agent=user_agent, referer=referer, proxy=proxy,
            prime_cookies=prime_cookies, aggressive=aggressive, use_browser=use_browser,
            cloudscraper_ok=CLOUDSCRAPER_OK, httpx_ok=HTTPX_OK, curlcffi_ok=CURLCFFI_OK, playwright_ok=PLAYWRIGHT_OK
        )

    try:
        delay = float(delay_raw)
    except Exception:
        delay = 1.0

    try:
        # 1) requests + anti-403 stack
        resp = polite_get(
            url,
            user_agent=user_agent,
            delay=delay,
            referer=referer,
            prime_cookies=prime_cookies,
            proxy=proxy,
            cookies_raw=cookies_raw,
            aggressive=aggressive,
        )
        method_used = "requests/aggressive" if aggressive else "requests"
        content_type = resp.headers.get("Content-Type", "")

        # 2) decide if blocked/weak and auto Playwright fallback
        blocked = (not getattr(resp, "ok", False)) or _looks_blocked(getattr(resp, "text", ""), getattr(resp, "status_code", 0))
        if (use_browser or blocked) and PLAYWRIGHT_OK:
            try:
                resp = browser_get(
                    url,
                    user_agent=user_agent or random.choice(SMART_UAS),
                    referer=referer,
                    timeout=90,
                    proxy=proxy,
                    cookies_raw=cookies_raw,  # pass cookies to Playwright
                )
                method_used = "playwright"
                content_type = resp.headers.get("Content-Type", "")
                blocked = False
            except Exception:
                # keep requests resp; will error below if still blocked
                pass

        if blocked:
            hints = []
            if not PLAYWRIGHT_OK:
                hints.append("install Playwright: pip install playwright && python -m playwright install chromium")
            hints += [
                "paste real cookies (DevTools) & a real Chrome UA",
                "use a residential proxy in the site’s country",
                "set Referer to https://www.google.com/",
            ]
            error = f"Request failed/blocked (status {getattr(resp,'status_code','?')}). " + " | ".join(hints)
            return render_template_string(
                HTML_TMPL,
                error=error, url=url, selector=selector, delay=delay,
                user_agent=user_agent, referer=referer, proxy=proxy,
                prime_cookies=prime_cookies, aggressive=aggressive, use_browser=use_browser, cookies=cookies_raw,
                cloudscraper_ok=CLOUDSCRAPER_OK, httpx_ok=HTTPX_OK, curlcffi_ok=CURLCFFI_OK, playwright_ok=PLAYWRIGHT_OK
            )

        title, meta_desc, headings, links, images = extract_summary(resp.text, resp.url)
        _LAST_LINKS = links[:]

        selector_matches = None
        if selector:
            soup = BeautifulSoup(resp.text, "html.parser")
            found = soup.select(selector)
            selector_matches = []
            for el in found:
                text = el.get_text(" ", strip=True)
                selector_matches.append(text if text else re.sub(r"\s+", " ", str(el))[:500])

        result = type("Res", (), dict(
            status_code=getattr(resp, "status_code", 200),
            content_type=content_type,
            final_url=resp.url,
            title=title,
            meta_description=meta_desc,
            headings=headings,
            links=links,
            images=images,
            selector=selector,
            selector_matches=selector_matches,
            method_used=method_used,
        ))
        return render_template_string(
            HTML_TMPL,
            result=result,
            url=url,
            selector=selector,
            delay=delay,
            user_agent=user_agent,
            referer=referer,
            proxy=proxy,
            prime_cookies=prime_cookies,
            aggressive=aggressive,
            use_browser=use_browser,
            cookies=cookies_raw,
            cloudscraper_ok=CLOUDSCRAPER_OK, httpx_ok=HTTPX_OK, curlcffi_ok=CURLCFFI_OK, playwright_ok=PLAYWRIGHT_OK
        )
    except requests.RequestException as e:
        error = f"Network error: {e}"
    except Exception as e:
        error = f"Unexpected error: {e}"

    return render_template_string(
        HTML_TMPL,
        error=error,
        url=url,
        selector=selector,
        delay=delay,
        user_agent=user_agent,
        referer=referer,
        proxy=proxy,
        prime_cookies=prime_cookies,
        aggressive=aggressive,
        use_browser=use_browser,
        cookies=cookies_raw,
        cloudscraper_ok=CLOUDSCRAPER_OK, httpx_ok=HTTPX_OK, curlcffi_ok=CURLCFFI_OK, playwright_ok=PLAYWRIGHT_OK
    )

@app.get("/download-links.csv")
def download_links():
    global _LAST_LINKS
    if not _LAST_LINKS:
        return redirect(url_for("home"))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["text", "href", "same_host"])
    for l in _LAST_LINKS:
        writer.writerow([l.get("text", ""), l.get("href", ""), l.get("same_host", False)])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="links.csv",
    )

@app.get("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    # pip install -r requirements.txt
    # Strong fallback: pip install playwright && python -m playwright install chromium
    app.run(host="0.0.0.0", port=5000, debug=True)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))  # Render provides $PORT
    app.run(host="0.0.0.0", port=port, debug=False)

