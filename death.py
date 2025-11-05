#!/usr/bin/env python3
# app.py — Requests-first scraper with optional Playwright fallback
# Run locally:  pip install -r requirements.txt && python app.py

import csv
import io
import re
import time
import random
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, redirect, url_for, jsonify
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

app = Flask(__name__)

# -------- Optional Playwright fallback (only used if installed) --------
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

HTML_TMPL = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Ultra Web Scraper</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:2rem;background:#0b0d10;color:#eaeef3}
  h1{font-size:1.6rem;margin:0 0 1rem}
  form{display:grid;gap:0.75rem;max-width:1100px}
  input,textarea,button,select{padding:0.7rem;border-radius:8px;border:1px solid #2a2f36;background:#12151b;color:#eaeef3}
  input:focus,textarea:focus,select:focus{outline:1px solid #3a7bfd}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;align-items:end}
  .card{background:#0f1217;border:1px solid #1b212a;border-radius:12px;padding:1rem;margin-top:1rem}
  a{color:#8ab4ff;word-break:break-all}
  code,pre{background:#0f1217;border:1px solid #1b212a;border-radius:8px;padding:0.5rem;display:block;overflow:auto}
  .muted{color:#aab3c2}
  .btn{cursor:pointer;background:#1a73e8;border:none}
  .row{display:flex;gap:0.5rem;flex-wrap:wrap}
  .badge{background:#11161e;border:1px solid #202735;border-radius:999px;padding:0.25rem 0.6rem;font-size:0.8rem}
  .danger{color:#ff6b6b}
  label.inline{display:flex;align-items:center;gap:.5rem}
</style>
</head>
<body>
<center><h1>DEATHROW GETS</h1></center>
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
      <input id="user_agent" name="user_agent" type="text" placeholder="Mozilla/5.0 ..." value="{{ user_agent or '' }}">
    </div>
  </div>
  <div class="grid">
    <div>
      <label for="referer">Referer (optional)</label>
      <input id="referer" name="referer" type="text" placeholder="https://example.com" value="{{ referer or '' }}">
    </div>
    <div>
      <label for="proxy">HTTP(S) Proxy (optional)</label>
      <input id="proxy" name="proxy" type="text" placeholder="http://user:pass@host:port" value="{{ proxy or '' }}">
    </div>
  </div>
  <div class="grid">
    <div>
      <label class="inline"><input type="checkbox" name="prime_cookies" value="1" {% if prime_cookies %}checked{% endif %}> Prime cookies (hit site root first)</label>
    </div>
    <div>
      <label class="inline"><input type="checkbox" name="use_browser" value="1" {% if use_browser %}checked{% endif %}> Use headless browser fallback</label>
      {% if not playwright_ok %}<span class="badge">Playwright not installed</span>{% else %}<span class="badge">Playwright ready</span>{% endif %}
    </div>
  </div>
  <div class="row">
    <button class="btn" type="submit">Scrape</button>
    <a class="badge" href="{{ url_for('home') }}">Reset</a>
  </div>
  <div class="muted">Tip: Paste messy URLs, I’ll auto-fix common issues (missing scheme, “wwwhttps”, slashes, etc.).</div>
</form>

{% if error %}
<div class="card"><strong class="danger">Error:</strong> {{ error }}</div>
{% endif %}

{% if result %}
<div class="card">
  <h2>Page Summary</h2>
  <div class="row">
    <span class="badge">Fetched URL: {{ result.final_url }}</span>
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
    <div class="row"><a class="badge" href="{{ url_for('download_links') }}">Download Links CSV</a></div>
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
    {% if result.selector_matches|length > 100 %}<p class="muted">Showing first 100 matches…</p>{% endif %}
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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

# -------- URL normalization --------
def normalize_url(u: str) -> str:
    if not u:
        return u
    u = u.strip().replace("\\", "/")
    u = re.sub(r'^(https?):/([^/])', r'\1://\2', u, flags=re.IGNORECASE)   # http:/ -> http://
    u = re.sub(r'^(https?):///*', r'\1://', u, flags=re.IGNORECASE)        # http://// -> http://
    u = re.sub(r'^(https?)(//)', r'\1://', u, flags=re.IGNORECASE)         # https// -> https://
    u = re.sub(r'^wwwhttps?://', 'https://', u, flags=re.IGNORECASE)       # wwwhttps:// -> https://
    if re.match(r'^www\.', u, flags=re.IGNORECASE):
        u = 'https://' + u
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', u):                    # <- dash escaped!
        u = 'https://' + u
    u = re.sub(r'^(https?://)/*', r'\1', u, flags=re.IGNORECASE)
    return u

def is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

# -------- Networking --------
def make_session(proxy: str | None = None):
    s = requests.Session()
    retries = Retry(
        total=3, backoff_factor=0.6,
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

def build_headers(user_agent: str, referer: str = "") -> dict:
    ua = (user_agent.strip() or random.choice(BROWSER_UAS))
    h = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        h["Referer"] = referer
    return h

def polite_get(url: str, user_agent: str = "", delay: float = 1.0, timeout: int = 20,
               referer: str = "", prime_cookies: bool = False, proxy: str | None = None):
    time.sleep(max(0.0, delay))
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = build_headers(user_agent=user_agent, referer=referer or origin)
    session = make_session(proxy)

    if prime_cookies:
        try:
            session.get(origin, headers=headers, timeout=timeout, allow_redirects=True)
            time.sleep(0.3)
        except requests.RequestException:
            pass

    resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if resp.status_code == 403:
        # soften retries with different UA/referer
        headers = build_headers(user_agent="", referer="")
        time.sleep(0.5)
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code == 403:
            headers = build_headers(user_agent="", referer=origin)
            time.sleep(0.4)
            resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    return resp

def browser_get(url: str, user_agent: str = "", timeout: int = 60, referer: str = "",
                proxy: str | None = None, selector: str | None = None):
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && python -m playwright install chromium")
    if "#" in url:
        url = url.split("#", 1)[0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx_args = {
            "viewport": {"width": 1366, "height": 768},
            "java_script_enabled": True,
            "timezone_id": "Africa/Nairobi",
            "locale": "en-US",
        }
        if proxy:
            ctx_args["proxy"] = {"server": proxy}
        if user_agent:
            ctx_args["user_agent"] = user_agent
        ctx = browser.new_context(**ctx_args)
        ctx.add_init_script("""Object.defineProperty(navigator, 'webdriver', {get: () => undefined});""")
        page = ctx.new_page()

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
        try:
            page.wait_for_load_state("load", timeout=int(timeout * 0.5) * 1000)
        except Exception:
            pass
        if selector:
            try:
                page.wait_for_selector(selector, timeout=int(timeout * 0.5) * 1000, state="attached")
            except Exception:
                pass
        time.sleep(0.8)
        try:
            page.evaluate("""() => { window.scrollBy(0, document.body.scrollHeight/2); }""")
        except Exception:
            pass
        time.sleep(0.5)

        html = page.content()
        final_url = page.url

        class R:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            text = html
            url = final_url
            ok = True
        ctx.close()
        browser.close()
        return R()

# -------- Parsing --------
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

# -------- Routes --------
@app.route("/", methods=["GET"])
def home():
    return render_template_string(HTML_TMPL, playwright_ok=PLAYWRIGHT_AVAILABLE)

@app.route("/scrape", methods=["POST"])
def scrape():
    global _LAST_LINKS
    _LAST_LINKS = []

    raw_url = (request.form.get("url") or "").strip()
    selector = (request.form.get("selector") or "").strip()
    delay_raw = (request.form.get("delay") or "1").strip()
    user_agent = (request.form.get("user_agent") or "").strip()
    referer = (request.form.get("referer") or "").strip()
    proxy = (request.form.get("proxy") or "").strip() or None
    prime_cookies = request.form.get("prime_cookies") == "1"
    use_browser = request.form.get("use_browser") == "1"

    url = normalize_url(raw_url)
    if not is_valid_url(url):
        error = f"Please provide a valid URL. You entered: “{raw_url}”."
        return render_template_string(HTML_TMPL, error=error, url=raw_url, selector=selector, playwright_ok=PLAYWRIGHT_AVAILABLE)

    try:
        delay = float(delay_raw)
    except Exception:
        delay = 1.0

    try:
        # 1) Try requests first
        resp = polite_get(url, user_agent=user_agent, delay=delay, referer=referer,
                          prime_cookies=prime_cookies, proxy=proxy)
        method_used = "requests"

        # 2) If blocked and user enabled fallback, try Playwright
        need_browser = (not resp.ok) or (resp.status_code in (401, 403)) or (resp.ok and len((resp.text or "").strip()) < 500)
        if need_browser and use_browser:
            if PLAYWRIGHT_AVAILABLE:
                resp = browser_get(
                    url,
                    user_agent=user_agent or random.choice(BROWSER_UAS),
                    timeout=75,
                    referer=referer,
                    proxy=proxy,
                    selector=selector if selector else None
                )
                method_used = "playwright"
            else:
                error = ("Request blocked and browser fallback not available. "
                         "Run: pip install playwright && python -m playwright install chromium")
                return render_template_string(
                    HTML_TMPL, error=error, url=url, selector=selector,
                    delay=delay, user_agent=user_agent, referer=referer, proxy=proxy,
                    prime_cookies=prime_cookies, use_browser=use_browser, playwright_ok=PLAYWRIGHT_AVAILABLE
                )

        content_type = resp.headers.get("Content-Type", "")
        if not resp.ok:
            error = f"Request failed with status {resp.status_code}. Try different UA/Referer, a proxy, or enable headless browser."
            return render_template_string(
                HTML_TMPL, error=error, url=url, selector=selector, delay=delay,
                user_agent=user_agent, referer=referer, proxy=proxy,
                prime_cookies=prime_cookies, use_browser=use_browser,
                playwright_ok=PLAYWRIGHT_AVAILABLE
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

        result = {
            "status_code": getattr(resp, "status_code", 200),
            "content_type": content_type,
            "final_url": resp.url,
            "title": title,
            "meta_description": meta_desc,
            "headings": headings,
            "links": links,
            "images": images,
            "selector": selector,
            "selector_matches": selector_matches,
            "method_used": method_used,
        }

        return render_template_string(HTML_TMPL,
            result=result, url=url, selector=selector, delay=delay,
            user_agent=user_agent, referer=referer, proxy=proxy,
            prime_cookies=prime_cookies, use_browser=use_browser,
            playwright_ok=PLAYWRIGHT_AVAILABLE)
    except requests.RequestException as e:
        error = f"Network error: {e}"
    except Exception as e:
        error = f"Unexpected error: {e}"

    return render_template_string(HTML_TMPL,
        error=error, url=url, selector=selector, delay=delay,
        user_agent=user_agent, referer=referer, proxy=proxy,
        prime_cookies=prime_cookies, use_browser=use_browser,
        playwright_ok=PLAYWRIGHT_AVAILABLE)

@app.route("/download-links.csv", methods=["GET"])
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
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")),
                     mimetype="text/csv", as_attachment=True,
                     download_name="links.csv")

# ---- Simple JSON API ----
@app.post("/api/scrape")
def api_scrape():
    payload = request.get_json(force=True, silent=True) or {}
    raw_url = (payload.get("url") or "").strip()
    selector = (payload.get("selector") or "").strip()
    use_browser = bool(payload.get("use_browser", False))
    user_agent = (payload.get("user_agent") or "").strip()
    referer = (payload.get("referer") or "").strip()
    proxy = (payload.get("proxy") or "").strip() or None
    prime_cookies = bool(payload.get("prime_cookies", False))
    delay = float(payload.get("delay", 1.0))

    url = normalize_url(raw_url)
    if not is_valid_url(url):
        return jsonify({"error": "invalid_url", "input": raw_url}), 400

    try:
        resp = polite_get(url, user_agent=user_agent, delay=delay, referer=referer,
                          prime_cookies=prime_cookies, proxy=proxy)
        method = "requests"
        need_browser = (not resp.ok) or (resp.status_code in (401, 403)) or (resp.ok and len((resp.text or "").strip()) < 500)
        if need_browser and use_browser:
            if not PLAYWRIGHT_AVAILABLE:
                return jsonify({"error": "playwright_not_installed"}), 503
            resp = browser_get(url, user_agent=user_agent or random.choice(BROWSER_UAS),
                               timeout=75, referer=referer, proxy=proxy, selector=selector or None)
            method = "playwright"

        if not resp.ok:
            return jsonify({"error": "http_error", "status": resp.status_code}), resp.status_code

        title, meta_desc, headings, links, images = extract_summary(resp.text, resp.url)

        selector_matches = None
        if selector:
            soup = BeautifulSoup(resp.text, "html.parser")
            found = soup.select(selector)
            selector_matches = []
            for el in found:
                text = el.get_text(" ", strip=True)
                selector_matches.append(text if text else re.sub(r"\s+", " ", str(el))[:500])

        return jsonify({
            "final_url": resp.url,
            "status_code": getattr(resp, "status_code", 200),
            "content_type": resp.headers.get("Content-Type", ""),
            "title": title,
            "meta_description": meta_desc,
            "headings": headings,
            "links": links,
            "images": images,
            "selector": selector,
            "selector_matches": selector_matches,
            "method_used": method,
        })
    except Exception as e:
        return jsonify({"error": "unexpected", "message": str(e)}), 500

@app.get("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
