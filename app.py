"""
LIVE CRICKET OBS OVERLAY — Cloud Web App v22
=============================================
Deploy to Railway / Render / any cloud.

Usage:
  Open in browser: https://your-app.railway.app/overlay?match=12345&squad=https://cricbuzz.com/cricket-match-squads/...
  OBS Browser Source: same URL, 1280x720
"""

import os, re, json, time, threading, logging
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string
from bs4 import BeautifulSoup
import requests as _req

from scraper_core import (
    parse, parse_json_api, blank_data, fetch_page, fetch_json_api,
    load_photo_cache, _photo_cache, _photo_lock, save_photo_cache,
    SCRAPE_INTERVAL, SESSION, HEADERS_MOB, HEADERS_API
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# ── Per-match state ───────────────────────────────────────────────────────────
_matches    = {}
_match_lock = threading.Lock()
SCRAPE_INTERVAL = 4

def get_or_create_match(match_id: str) -> dict:
    with _match_lock:
        if match_id not in _matches:
            _matches[match_id] = {
                "data": blank_data(),
                "last_fetch": 0,
                "error": "",
                "fetching": False,
            }
        return _matches[match_id]

def scrape_match(match_id: str):
    """Background thread: JSON API first, HTML scrape fallback."""
    html_url = f"https://m.cricbuzz.com/cricket-commentary/{match_id}"
    log.info(f"[{match_id}] Scraper thread started")
    errors = 0
    while True:
        try:
            state = get_or_create_match(match_id)
            data  = dict(state["data"])

            # Strategy 1: Cricbuzz JSON APIs (fast, structured)
            api_data = fetch_json_api(match_id)
            if api_data:
                data = parse_json_api(api_data, data)
                log.info(f"[{match_id}] API ✓  {data['team1'].get('name','?')} "
                         f"{data['team1'].get('score','?')} vs "
                         f"{data['team2'].get('name','?')} {data['team2'].get('score','?')} "
                         f"CRR={data.get('crr','?')}")
            else:
                # Strategy 2: HTML scrape fallback
                html = fetch_page(html_url)
                data = parse(html, data)
                log.info(f"[{match_id}] HTML ✓  {data['team1'].get('name','?')} "
                         f"{data['team1'].get('score','?')} vs "
                         f"{data['team2'].get('name','?')} {data['team2'].get('score','?')}")

            data["last_updated"] = datetime.now().strftime("%H:%M:%S")
            with _match_lock:
                _matches[match_id]["data"]       = data
                _matches[match_id]["last_fetch"]  = time.time()
                _matches[match_id]["error"]       = ""
            errors = 0
        except Exception as e:
            errors += 1
            log.warning(f"[{match_id}] Error ({errors}): {e}")
            with _match_lock:
                if match_id in _matches:
                    _matches[match_id]["error"] = str(e)
            if errors >= 5:
                log.warning(f"[{match_id}] 5 errors — sleeping 15s")
                time.sleep(15); errors = 0
        time.sleep(SCRAPE_INTERVAL)

_scraper_threads = {}

def ensure_scraper(match_id: str):
    if match_id not in _scraper_threads or not _scraper_threads[match_id].is_alive():
        t = threading.Thread(target=scrape_match, args=(match_id,), daemon=True)
        t.start()
        _scraper_threads[match_id] = t
        log.info(f"[{match_id}] Started scraper thread")

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

@app.route("/overlay")
def overlay():
    """Serve the overlay with match ID baked in (reference-style clean approach)."""
    match_id  = request.args.get("match", "").strip()
    squad_url = request.args.get("squad", "").strip()
    m = re.search(r'\d+', match_id)
    if not m:
        return "Missing ?match=ID parameter. Example: /overlay?match=12345", 400
    match_id = m.group()

    ensure_scraper(match_id)
    if squad_url:
        threading.Thread(target=scrape_playing11_bg, args=(match_id, squad_url), daemon=True).start()

    html_file = os.path.join(os.path.dirname(__file__), "livematch_v20.html")
    if not os.path.exists(html_file):
        return "livematch_v20.html not found", 500
    with open(html_file, encoding="utf-8") as f:
        html = f.read()

    squad_safe = squad_url.replace("\\", "").replace("'", "")

    # ── Bake match ID directly into the JS (reference approach — simple & reliable)
    # Replace the poll fetch URL with a hardcoded match ID
    html = html.replace(
        "fetch('/data/'+currentMatchId+'?t='+Date.now(),{signal:AbortSignal.timeout(3000)})",
        f"fetch('/data/{match_id}?t='+Date.now(),{{signal:AbortSignal.timeout(3000)}})"
    )
    # Pre-set JS variables so setup screen auto-hides on load
    html = html.replace(
        "let currentMatchId='';",
        f"let currentMatchId='{match_id}';"
    )
    html = html.replace(
        "let currentSquadUrl='';",
        f"let currentSquadUrl='{squad_safe}';"
    )
    # Hide the setup screen by default when served from server
    html = html.replace(
        'id="matchSetup"',
        'id="matchSetup" style="display:none"'
    )

    return html

@app.route("/data/<match_id>")
def data_endpoint(match_id):
    match_id = re.sub(r'[^\d]', '', match_id)
    if not match_id:
        return jsonify({}), 400
    ensure_scraper(match_id)
    state = get_or_create_match(match_id)
    d = state["data"]
    # If scraper hasn't populated data yet, do a quick synchronous fetch right now
    if not d.get("team1", {}).get("name") and not d.get("last_updated"):
        try:
            api_data = fetch_json_api(match_id)
            if api_data:
                d = parse_json_api(api_data, blank_data())
                d["last_updated"] = datetime.now().strftime("%H:%M:%S")
                with _match_lock:
                    _matches[match_id]["data"] = d
                    _matches[match_id]["last_fetch"] = time.time()
        except Exception as e:
            log.warning(f"[{match_id}] Sync fetch failed: {e}")
    resp = jsonify(d)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.route("/squads/<match_id>")
def squad_endpoint(match_id):
    match_id = re.sub(r'[^\d]', '', match_id)
    with _match_lock:
        squad = _matches.get(match_id, {}).get("playing11", {})
    resp = jsonify(squad)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.route("/status")
def status():
    with _match_lock:
        info = {}
        for mid, state in _matches.items():
            d = state["data"]
            info[mid] = {
                "team1":      d["team1"].get("name","?"),
                "team2":      d["team2"].get("name","?"),
                "score1":     d["team1"].get("score","?"),
                "score2":     d["team2"].get("score","?"),
                "crr":        d.get("crr","?"),
                "last_fetch": datetime.fromtimestamp(state["last_fetch"]).strftime("%H:%M:%S") if state["last_fetch"] else "never",
                "error":      state["error"],
            }
    return jsonify(info)

@app.route("/test")
def test_page():
    """Diagnostic test page — open this to see exactly what broken."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "test.html"), encoding="utf-8") as f:
            return f.read()
    except:
        return "test.html not found", 404

@app.route("/debug/<match_id>")
def debug_endpoint(match_id):
    """Show what the scraper is currently producing for a match."""
    match_id = re.sub(r'[^\d]', '', match_id)
    
    # Try JSON API
    api_data = fetch_json_api(match_id)
    api_ok = bool(api_data)
    
    # Try HTML page
    html_ok = False
    html_data = blank_data()
    try:
        html = fetch_page(f"https://m.cricbuzz.com/cricket-commentary/{match_id}")
        html_data = parse(html, html_data)
        html_ok = bool(html_data.get("team1",{}).get("name"))
    except Exception as e:
        html_data["_error"] = str(e)
    
    # Current stored data
    with _match_lock:
        stored = _matches.get(match_id, {}).get("data", {})
    
    result = {
        "json_api_available": api_ok,
        "html_scraper_ok": html_ok,
        "current_stored": stored,
        "html_parsed": {
            "team1": html_data.get("team1"),
            "team2": html_data.get("team2"),
            "crr": html_data.get("crr"),
            "batsman1": html_data.get("batsman1"),
            "batsman2": html_data.get("batsman2"),
            "bowler": html_data.get("bowler"),
            "match_status": html_data.get("match_status"),
            "error": html_data.get("_error"),
        } if not api_ok else None,
        "api_parsed": parse_json_api(api_data, blank_data()) if api_ok else None,
    }
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store"
    return resp

# ── Playing XI background scraper ─────────────────────────────────────────────

def scrape_playing11_bg(match_id, squad_url):
    try:
        r = SESSION.get(squad_url, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        all_players = []
        for ul in soup.find_all(["ul", "div"]):
            cls = " ".join(ul.get("class", []))
            if "squad" in cls.lower() or "player" in cls.lower():
                players_in = ul.find_all("a", href=lambda h: h and "/profiles/" in h)
                if len(players_in) >= 5:
                    all_players.append(players_in)

        team_players_list = []
        for pl_list in all_players[:2]:
            team_players = []
            for a in pl_list:
                name = a.get_text(strip=True)
                if not name or len(name) < 3: continue
                role_el = a.find_next(class_=lambda c: c and "role" in " ".join(c).lower())
                role = role_el.get_text(strip=True) if role_el else "Player"
                img = a.find("img")
                photo = ""
                if img:
                    src = img.get("src", "")
                    if "cricbuzz" in src: photo = src.replace("d=low", "d=high")
                team_players.append({"name": name, "role": role, "photo": photo})
            if team_players:
                team_players_list.append(team_players)

        # Fallback: extract from page scripts
        if not team_players_list:
            for script in soup.find_all("script"):
                content = script.string or ""
                if "playing11" in content.lower() or "squad" in content.lower():
                    names = re.findall(r'"name"\s*:\s*"([A-Z][a-zA-Z\s\.]{2,30})"', content)
                    if len(names) >= 11:
                        chunk1 = [{"name": n, "role": "Player", "photo": ""} for n in names[:11]]
                        chunk2 = [{"name": n, "role": "Player", "photo": ""} for n in names[11:22]]
                        if chunk1: team_players_list.append(chunk1)
                        if chunk2: team_players_list.append(chunk2)
                        break

        team_names = []
        for h in soup.find_all(["h1","h2","h3"]):
            t = h.get_text(strip=True)
            if " vs " in t.lower() or " v " in t.lower():
                parts = re.split(r'\s+vs?\s+', t, flags=re.I)
                if len(parts) >= 2:
                    team_names = [parts[0].strip(), parts[1].strip()]
                break

        playing11 = {
            "team1": {"name": team_names[0] if team_names else "Team 1",
                      "players": team_players_list[0] if team_players_list else []},
            "team2": {"name": team_names[1] if len(team_names) > 1 else "Team 2",
                      "players": team_players_list[1] if len(team_players_list) > 1 else []}
        }

        with _match_lock:
            if match_id not in _matches:
                _matches[match_id] = {"data": blank_data(), "last_fetch": 0, "error": "", "fetching": False}
            _matches[match_id]["playing11"] = playing11

        log.info(f"[{match_id}] Playing XI: {len(playing11['team1']['players'])} + {len(playing11['team2']['players'])} players")

    except Exception as e:
        log.warning(f"[{match_id}] Playing XI scrape failed: {e}")

# ── Landing page ──────────────────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🏏 Sports Adda67 — Live Cricket Overlay</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#05080f;color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.card{background:#0a1628;border:2px solid #FF6B00;border-radius:16px;padding:40px 48px;width:580px;max-width:95vw;}
h1{font-size:28px;color:#FFD700;margin-bottom:6px;letter-spacing:1px;}
.sub{color:rgba(255,255,255,.5);font-size:14px;margin-bottom:28px;}
label{font-size:13px;color:rgba(255,215,0,.8);font-weight:700;letter-spacing:1px;display:block;margin-bottom:8px;}
input{width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.2);border-radius:8px;color:#fff;font-size:18px;padding:10px 16px;outline:none;margin-bottom:16px;}
input:focus{border-color:#FF6B00;}
.btn{width:100%;background:linear-gradient(90deg,#FF6B00,#FFD700);color:#000;font-weight:900;font-size:16px;letter-spacing:1px;padding:14px;border:none;border-radius:8px;cursor:pointer;}
.btn:hover{opacity:.9;}
.tip{margin-top:20px;font-size:12px;color:rgba(255,255,255,.35);line-height:1.8;}
.tip b{color:rgba(255,215,0,.6);}
.links{margin-top:16px;display:flex;gap:10px;}
.lbtn{flex:1;text-align:center;padding:8px;border-radius:6px;font-size:12px;font-weight:700;text-decoration:none;letter-spacing:1px;}
.obs{background:rgba(0,176,255,.15);color:#00B0FF;border:1px solid rgba(0,176,255,.3);}
.preview{background:rgba(255,107,0,.15);color:#FF6B00;border:1px solid rgba(255,107,0,.3);}
</style>
</head>
<body>
<div class="card">
  <h1>🏏 Sports Adda67 Cricket Overlay</h1>
  <div class="sub">Live scores · Auto-updating · Playing XI · H2H · Venue & Weather</div>
  <form onsubmit="go(event)">
    <label>CRICBUZZ MATCH ID OR URL</label>
    <input id="mid" placeholder="e.g. 148765  or paste full cricbuzz URL" autocomplete="off">
    <label>SQUAD URL (optional — for Playing XI)</label>
    <input id="squad" placeholder="https://www.cricbuzz.com/cricket-match-squads/12345/..." style="font-size:13px;">
    <button class="btn" type="submit">▶ OPEN OVERLAY</button>
  </form>
  <div class="links" id="links" style="display:none">
    <a class="lbtn obs" id="obsLink" href="#" target="_blank">📺 Open in OBS</a>
    <a class="lbtn preview" id="previewLink" href="#" target="_blank">🔍 Preview in Browser</a>
  </div>
  <div class="tip">
    <b>Match ID:</b> cricbuzz.com/live-cricket-scores/<b>12345</b>/india-vs...<br>
    <b>Squad URL:</b> cricbuzz.com/cricket-match-squads/<b>12345</b>/match-name<br>
    <b>OBS:</b> Browser Source → paste overlay URL → 1280×720<br>
    <b>Debug:</b> visit /status for live scraper state · /debug/MATCHID for raw API data
  </div>
</div>
<script>
function go(e) {
  e.preventDefault();
  const raw = document.getElementById('mid').value.trim();
  const squad = document.getElementById('squad').value.trim();
  const m = raw.match(/[0-9]+/);
  if(!m) { alert('Please enter a match ID or Cricbuzz URL'); return; }
  const id = m[0];
  let url = window.location.origin + '/overlay?match=' + id;
  if(squad) url += '&squad=' + encodeURIComponent(squad);
  document.getElementById('obsLink').href = url;
  document.getElementById('previewLink').href = url;
  document.getElementById('links').style.display = 'flex';
}
</script>
</body>
</html>"""

# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_photo_cache()
    port = int(os.environ.get("PORT", 8000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
