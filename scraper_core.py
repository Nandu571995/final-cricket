"""
LIVE CRICKET OBS OVERLAY — scraper_core.py
==========================================
Data source priority:
  1. Cricbuzz JSON API  — /api/cricket-match/{id}/mini-scorecard  (primary)
  2. Cricbuzz HTML page — regex on Next.js embedded JSON           (fallback)

Photos: Cricbuzz search API + permanent local cache
"""

import re, json, time, threading, os, requests
from datetime import datetime
from bs4 import BeautifulSoup

SCRAPE_INTERVAL  = 4
PHOTO_CACHE_FILE = "player_photos.json"

# ── HTTP sessions ──────────────────────────────────────────────────────────────

HEADERS_MOB = {
    "User-Agent":      "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer":         "https://m.cricbuzz.com/",
}

HEADERS_API = {
    "User-Agent":          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":              "application/json, text/plain, */*",
    "Accept-Language":     "en-US,en;q=0.9",
    "Referer":             "https://www.cricbuzz.com/",
    "x-cricbuzz-client":   "app",
    "x-app-version":       "6.06",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS_MOB)

# ── Photo cache ────────────────────────────────────────────────────────────────

_photo_cache       = {}
_photo_lock        = threading.Lock()
_player_slug_cache = {}

def load_photo_cache():
    global _photo_cache
    try:
        if os.path.exists(PHOTO_CACHE_FILE):
            with open(PHOTO_CACHE_FILE, "r") as f:
                _photo_cache = json.load(f)
            print(f"  Loaded {len(_photo_cache)} cached player photos.")
    except:
        pass

def save_photo_cache():
    try:
        with open(PHOTO_CACHE_FILE, "w") as f:
            json.dump(_photo_cache, f, indent=2)
    except:
        pass

def get_photo(name):
    if not name or len(name) < 3:
        return ""
    with _photo_lock:
        if name in _photo_cache:
            return _photo_cache[name]
    url = fetch_photo_url(name)
    with _photo_lock:
        _photo_cache[name] = url
        save_photo_cache()
    return url

def fetch_photo_url(name):
    try:
        if name in _player_slug_cache:
            prof_id, slug = _player_slug_cache[name]
            u = _scrape_profile_photo(prof_id, slug)
            if u: return u
        query   = name.strip().lower().replace(" ", "+")
        api_url = f"https://www.cricbuzz.com/api/cricket-search/v2/search?query={query}&start=0&limit=5"
        r       = requests.get(api_url, headers=HEADERS_API, timeout=8)
        r.raise_for_status()
        data    = r.json()
        results = data.get("results", []) or data.get("entity", []) or []
        for item in results:
            if str(item.get("type","")).lower() != "player": continue
            title = item.get("title","") or item.get("name","")
            if not _names_match(name, title): continue
            image_id = (item.get("imageId") or item.get("faceImageId") or item.get("imgId") or item.get("id"))
            slug     = item.get("slug") or _name_to_slug(name)
            if image_id:
                return f"https://static.cricbuzz.com/a/img/v1/i1/c{image_id}/{slug}.jpg?d=high&p=gthumb"
        for item in results:
            if str(item.get("type","")).lower() != "player": continue
            pid  = item.get("id") or item.get("playerId")
            slug = item.get("slug") or _name_to_slug(name)
            if pid: return _scrape_profile_photo(pid, slug)
    except:
        pass
    return ""

def _scrape_profile_photo(pid, slug):
    try:
        r    = requests.get(f"https://www.cricbuzz.com/profiles/{pid}/{slug}", headers=HEADERS_API, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src","")
            if "gthumb" in src or "p=det" in src:
                if slug.split("-")[0] in src or slug.split("-")[-1] in src:
                    return src.replace("d=low","d=high")
        for img in soup.find_all("img"):
            src = img.get("src","")
            if slug[:4] in src and "cricbuzz" in src:
                return src.replace("d=low","d=high")
    except:
        pass
    return ""

def _names_match(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    if a == b: return True
    ap, bp = a.split(), b.split()
    if ap and bp and ap[-1] == bp[-1]: return True
    if len(ap) >= 2 and len(bp) >= 2:
        if ap[0] == bp[0] and ap[1][0] == bp[1][0]: return True
    return False

def _name_to_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")

def fetch_photos_async(names):
    def _fetch():
        for name in names:
            if name and name not in _photo_cache:
                get_photo(name)
    threading.Thread(target=_fetch, daemon=True).start()

# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_int(v):
    try:    return int(re.sub(r"[^\d]", "", str(v)) or "0")
    except: return 0

def fetch_page(url):
    r = SESSION.get(url, timeout=10)
    r.raise_for_status()
    return r.text

def blank_data():
    return {
        "team1":          {"name":"","score":"","overs":"","flag_img":"","flag_manual":""},
        "team2":          {"name":"","score":"","overs":"","flag_img":"","flag_manual":""},
        "crr":"", "rrr":"", "target":"", "need":"", "partnership":"",
        "match_status":   "LIVE",
        "yet_to_bat":"",  "last_wicket":"",
        "current_over":   0,
        "last_over_balls":[], "current_ball":"",
        "prev_over_balls":[],
        "batsman1":{},    "batsman2":{},    "bowler":{},
        "match_format":   "T20",
        "series_name":"", "last_updated":"",
    }

def load_manual_flags():
    try:
        if os.path.exists("data.json"):
            with open("data.json","r") as f: d = json.load(f)
            return (d.get("team1",{}).get("flag_manual",""), d.get("team2",{}).get("flag_manual",""))
    except: pass
    return "",""

# ── PRIMARY: Cricbuzz JSON API ─────────────────────────────────────────────────

def fetch_json_api(match_id):
    """
    Call Cricbuzz internal REST APIs (same ones their app uses).
    Returns merged dict or None.
    """
    result = {}
    for url in [
        f"https://www.cricbuzz.com/api/cricket-match/{match_id}/mini-scorecard",
        f"https://www.cricbuzz.com/api/cricket-match/{match_id}/live-score",
    ]:
        try:
            r = SESSION.get(url, headers=HEADERS_API, timeout=8)
            if r.status_code == 200:
                d = r.json()
                if d: result.update(d)
        except:
            pass
    return result if result else None

def parse_json_api(api, data):
    """
    Parse Cricbuzz mini-scorecard / live-score JSON response.

    JSON structure:
      matchHeader.{matchFormat, seriesDesc, status, team1.name, team2.name}
      matchScoreDetails.inningsScoreList[].{batTeamName, score, wickets, overs, inningsId}
      miniscore.{currentRunRate, requiredRunRate, target, overs}
      miniscore.partnerShip.{runs, balls}
      miniscore.lastWicket
      miniscore.recentOvsStats            (string "1 0 W 4 .")
      miniscore.batsmanStriker / batsmanNonStriker
        {batName, batRuns, batBalls, batFours, batSixes, batStrikeRate, playerUrl}
      miniscore.bowlerStriker / bowlerNonStriker
        {bowlName, bowlOvs, bowlMaidens, bowlRuns, bowlWkts, bowlEcon, playerUrl}
    """
    bat_names = []
    ms   = api.get("miniscore") or {}
    mhdr = api.get("matchHeader") or {}
    msd  = api.get("matchScoreDetails") or {}

    # Format / Series
    fmt = (mhdr.get("matchFormat") or mhdr.get("matchType") or "").upper()
    if fmt: data["match_format"] = fmt
    series = mhdr.get("seriesDesc") or mhdr.get("seriesName") or ""
    if series: data["series_name"] = series[:80]

    # Status
    status = ms.get("customStatus") or mhdr.get("status") or msd.get("customStatus") or ""
    if status: data["match_status"] = str(status).strip()[:50]

    # Team scores from innings list
    innings = msd.get("inningsScoreList") or []
    for inn in innings:
        inn_id = inn.get("inningsId", 0)
        tname  = inn.get("batTeamName") or inn.get("teamName") or ""
        score  = inn.get("score", "")
        wkts   = inn.get("wickets", "")
        overs  = str(inn.get("overs", ""))
        if tname:
            key = "team1" if inn_id in (1, 3) else "team2"
            data[key]["name"]  = tname
            data[key]["score"] = f"{score}-{wkts}" if score != "" else ""
            data[key]["overs"] = overs

    # Fallback team names
    if not data["team1"]["name"]:
        t1 = mhdr.get("team1") or {}
        t2 = mhdr.get("team2") or {}
        if t1.get("name"): data["team1"]["name"] = t1["name"]
        if t2.get("name"): data["team2"]["name"] = t2["name"]

    # CRR / RRR / Target
    if ms.get("currentRunRate"): data["crr"] = str(ms["currentRunRate"])
    if ms.get("requiredRunRate"): data["rrr"] = str(ms["requiredRunRate"])
    if ms.get("target"): data["target"] = str(ms["target"])

    # Partnership
    pship = ms.get("partnerShip") or {}
    if isinstance(pship, dict):
        pr = pship.get("runs",""); pb = pship.get("balls","")
        if pr != "": data["partnership"] = f"{pr}({pb})"
    elif isinstance(pship, str) and pship:
        data["partnership"] = pship

    # Last wicket
    lw = ms.get("lastWicket") or ""
    if lw: data["last_wicket"] = str(lw)[:100]

    # Yet to bat
    ytb = ms.get("yetToBat") or ""
    if isinstance(ytb, list): ytb = ", ".join(str(x) for x in ytb)
    if ytb: data["yet_to_bat"] = str(ytb)[:200]

    # Over balls from recentOvsStats
    recent = ms.get("recentOvsStats") or ""
    if recent:
        tokens = re.findall(r"W|WD|NB|LB|\d", str(recent).upper())
        if tokens:
            data["last_over_balls"] = tokens[-6:]
            data["current_ball"]    = tokens[-1]

    ov_num = ms.get("overs") or ms.get("currentOver") or 0
    try:    data["current_over"] = int(float(str(ov_num)))
    except: pass

    # ── Batsmen — try every known Cricbuzz API field name variant ────────────
    def _make_batter(p):
        if not isinstance(p, dict) or not p: return None
        # Field name variants across Cricbuzz API versions:
        # v1: batName/batRuns/batBalls/batFours/batSixes/batStrikeRate
        # v2: name/runs/balls/fours/sixes/strikeRate  
        # v3: batsman/score (very old)
        name = (p.get("batName") or p.get("name") or p.get("batsman") or "").strip()
        if not name or len(name) < 2: return None
        runs  = safe_int(p.get("batRuns")  or p.get("runs")  or p.get("score") or 0)
        balls = safe_int(p.get("batBalls") or p.get("balls") or 0)
        fours = safe_int(p.get("batFours") or p.get("fours") or p.get("4s")   or 0)
        sixes = safe_int(p.get("batSixes") or p.get("sixes") or p.get("6s")   or 0)
        sr_raw = p.get("batStrikeRate") or p.get("strikeRate") or p.get("sr") or ""
        sr = str(sr_raw) if sr_raw else (f"{runs*100/balls:.2f}" if balls else "0.00")
        photo = _photo_cache.get(name, "")
        bat_names.append(name)
        for url_key in ("playerUrl","profileUrl","url"):
            if p.get(url_key):
                m = re.search(r"/profiles/(\d+)/([a-z0-9-]+)", str(p[url_key]))
                if m and name not in _player_slug_cache:
                    _player_slug_cache[name] = (m.group(1), m.group(2))
                break
        return {"name":name,"runs":runs,"balls":balls,"fours":fours,
                "sixes":sixes,"sr":sr,"on_strike":False,"photo":photo}

    # Try multiple key names for batsmen objects
    striker_obj = (ms.get("batsmanStriker") or ms.get("striker") or
                   ms.get("batsman1") or ms.get("batsmanOne") or {})
    nonstriker_obj = (ms.get("batsmanNonStriker") or ms.get("nonStriker") or
                      ms.get("batsman2") or ms.get("batsmanTwo") or {})
    b1 = _make_batter(striker_obj)
    b2 = _make_batter(nonstriker_obj)
    if b1: data["batsman1"] = b1
    if b2: data["batsman2"] = b2

    # ── Bowler — try every known field name variant ───────────────────────────
    bw = (ms.get("bowlerStriker") or ms.get("bowlerNonStriker") or
          ms.get("bowler") or ms.get("currentBowler") or {})
    if isinstance(bw, dict) and bw:
        bname = (bw.get("bowlName") or bw.get("name") or bw.get("bowler") or "").strip()
        if bname and len(bname) >= 2:
            bovs  = str(bw.get("bowlOvs") or bw.get("overs") or bw.get("bowlOvers") or "0")
            bmdn  = safe_int(bw.get("bowlMaidens") or bw.get("maidens") or bw.get("maiden") or 0)
            bruns = safe_int(bw.get("bowlRuns")    or bw.get("runs")    or bw.get("bowlR")  or 0)
            bwkts = safe_int(bw.get("bowlWkts")    or bw.get("wickets") or bw.get("bowlW")  or 0)
            beco_raw = bw.get("bowlEcon") or bw.get("economy") or bw.get("eco") or ""
            try:    beco = f"{bruns/float(bovs):.2f}" if float(bovs) > 0 else "0.00"
            except: beco = str(beco_raw) if beco_raw else "0.00"
            photo = _photo_cache.get(bname, "")
            for url_key in ("playerUrl","profileUrl","url"):
                if bw.get(url_key):
                    m = re.search(r"/profiles/(\d+)/([a-z0-9-]+)", str(bw[url_key]))
                    if m and bname not in _player_slug_cache:
                        _player_slug_cache[bname] = (m.group(1), m.group(2))
                    break
            data["bowler"] = {"name":bname,"overs":bovs,"maidens":bmdn,
                              "runs":bruns,"wickets":bwkts,"economy":beco,"photo":photo}
            bat_names.append(bname)

    # Patch photos
    for key in ["batsman1","batsman2","bowler"]:
        p = data.get(key, {})
        if p.get("name") and not p.get("photo"):
            cached = _photo_cache.get(p["name"],"")
            if cached: data[key]["photo"] = cached

    uncached = [n for n in set(bat_names) if n and n not in _photo_cache]
    if uncached: fetch_photos_async(uncached)

    return data

# ── FALLBACK: HTML scrape with regex ──────────────────────────────────────────

def parse(html, data):
    """
    Fallback: extract data from Cricbuzz HTML using regex on embedded Next.js JSON.
    Does NOT rely on CSS class names (which Cricbuzz changes frequently).
    """
    bat_names = []

    # Title / series
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if title_m:
        t = re.sub(r"(?i)cricket commentary\s*\|\s*", "", title_m.group(1)).strip()
        if t: data["series_name"] = t[:80]

    # Match format
    for fmt in ["T20I","T20","ODI","Test","T10"]:
        if re.search(r"\b" + fmt + r"\b", html, re.I):
            data["match_format"] = fmt.upper(); break

    # Meta description for team scores
    desc_m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not desc_m:
        desc_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', html, re.I)
    desc = re.sub(r"\s+", " ", desc_m.group(1) if desc_m else "")

    if not data["team1"]["name"]:
        dm = re.search(
            r"Follow\s+([A-Z][A-Za-z\s]{1,20}?)\s+(\d+)/(\d+)\s*\(\s*([\d.]+)\s*\)"
            r"\s+vs\s+([A-Z][A-Za-z\s]{1,20}?)\s+(\d+)/(\d+)", desc)
        if dm:
            data["team1"].update({"name":dm.group(1).strip(),"score":f"{dm.group(2)}-{dm.group(3)}","overs":dm.group(4)})
            data["team2"].update({"name":dm.group(5).strip(),"score":f"{dm.group(6)}-{dm.group(7)}"})

    # Status
    r1 = re.search(r"([A-Z][a-zA-Z\s]{2,20}?\s+won by\s+\d+\s+(?:wkts?|runs?)[^<\n,]{0,20})", html)
    if r1: data["match_status"] = r1.group(1).strip()[:50]
    else:
        r2 = re.search(r"\b(Innings Break|Rain Delay|Stumps|Match Drawn|Match Tied)\b", html, re.I)
        if r2: data["match_status"] = r2.group(1).strip()

    # Find the biggest Next.js script containing live data
    best = ""
    for sm in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        c = sm.group(1)
        if "currentRunRate" in c and ("batsmanStriker" in c or "batName" in c):
            if len(c) > len(best): best = c

    if best:
        s = best

        # CRR / RRR / Target from numeric values
        for key, field in [("currentRunRate","crr"),("requiredRunRate","rrr"),("target","target")]:
            m = re.search(r'(?:\\*)"' + key + r'(?:\\*)"\s*:\s*([\d.]+)', s)
            if m and not data[field]: data[field] = m.group(1)

        # Partnership
        pb = re.search(r'"partnerShip"[^}]{0,100}"runs"\s*:\s*(\d+)[^}]{0,60}"balls"\s*:\s*(\d+)', s)
        if not pb:
            pb = re.search(r"partnerShip.{0,60}?runs.{0,10}?:(\d+).{0,40}?balls.{0,10}?:(\d+)", s)
        if pb: data["partnership"] = f"{pb.group(1)}({pb.group(2)})"

        # Custom status
        cs = re.search(r'"customStatus"\s*:\s*"([^"\\]{2,80})"', s)
        if not cs:
            cs = re.search(r'customStatus[^:]*:[^"\']*["\']([^"\'\\]{2,80})["\']', s)
        if cs:
            val = cs.group(1).strip()
            if val: data["match_status"] = val[:50]

        # Last wicket
        lw = re.search(r'"lastWicket"\s*:\s*"([^"\\]{5,150})"', s)
        if lw: data["last_wicket"] = lw.group(1)[:100]

        # Recent over balls
        rov = re.search(r'"recentOvsStats"\s*:\s*"([^"]{1,80})"', s)
        if rov:
            tokens = re.findall(r"W|WD|NB|LB|\d", rov.group(1).upper())
            if tokens:
                data["last_over_balls"] = tokens[-6:]
                data["current_ball"]    = tokens[-1]

        # Batsmen
        def _extract_batter(key):
            idx = s.find('"' + key + '"')
            if idx < 0: return None
            chunk = s[idx:idx+800]
            nm = re.search(r'"(?:batName|name)"\s*:\s*"([A-Z][^"\\]{2,40})"', chunk)
            if not nm: return None
            name  = nm.group(1).strip()
            def _n(k): m=re.search(r'"'+k+r'"\s*:\s*(\d+)',chunk); return safe_int(m.group(1)) if m else 0
            def _s(k): m=re.search(r'"'+k+r'"\s*:\s*"?([\d.]+)"?',chunk); return m.group(1) if m else ""
            runs=_n("batRuns"); balls=_n("batBalls"); fours=_n("batFours"); sixes=_n("batSixes")
            sr=_s("batStrikeRate") or (f"{runs*100/balls:.2f}" if balls else "0.00")
            photo=_photo_cache.get(name,"")
            bat_names.append(name)
            return {"name":name,"runs":runs,"balls":balls,"fours":fours,"sixes":sixes,"sr":sr,"on_strike":False,"photo":photo}

        b1 = _extract_batter("batsmanStriker")
        b2 = _extract_batter("batsmanNonStriker")
        if b1: data["batsman1"] = b1
        if b2: data["batsman2"] = b2

        # Bowler
        for bkey in ["bowlerStriker","bowlerNonStriker"]:
            idx = s.find('"' + bkey + '"')
            if idx >= 0:
                chunk = s[idx:idx+600]
                nm = re.search(r'"(?:bowlName|name)"\s*:\s*"([A-Z][^"\\]{2,40})"', chunk)
                if nm:
                    bname = nm.group(1).strip()
                    def _n(k): m=re.search(r'"'+k+r'"\s*:\s*(\d+)',chunk); return safe_int(m.group(1)) if m else 0
                    def _s(k): m=re.search(r'"'+k+r'"\s*:\s*"?([\d.]+)"?',chunk); return m.group(1) if m else ""
                    bovs  = _s("bowlOvs") or _s("overs") or "0"
                    bmdn  = _n("bowlMaidens")
                    bruns = _n("bowlRuns")
                    bwkts = _n("bowlWkts")
                    try:    beco = f"{bruns/float(bovs):.2f}" if float(bovs) > 0 else "0.00"
                    except: beco = _s("bowlEcon") or "0.00"
                    photo = _photo_cache.get(bname,"")
                    data["bowler"] = {"name":bname,"overs":bovs,"maidens":bmdn,"runs":bruns,"wickets":bwkts,"economy":beco,"photo":photo}
                    bat_names.append(bname)
                    break

        # Current over number
        ov_m = re.search(r'"overs"\s*:\s*([\d.]+)', s)
        if ov_m:
            try: data["current_over"] = int(float(ov_m.group(1)))
            except: pass

    # CRR / RRR plain text fallbacks
    if not data["crr"]:
        m = re.search(r"CRR[:\s]*([\d.]+)", html, re.I)
        if m: data["crr"] = m.group(1)
    if not data["rrr"]:
        m = re.search(r"RRR[:\s]*([\d.]+)", html, re.I)
        if m: data["rrr"] = m.group(1)
    if not data["target"]:
        m = re.search(r"[Tt]arget[:\s]*(\d+)", html)
        if m: data["target"] = m.group(1)

    # Patch photos
    for key in ["batsman1","batsman2","bowler"]:
        p = data.get(key, {})
        if p.get("name") and not p.get("photo"):
            cached = _photo_cache.get(p["name"],"")
            if cached: data[key]["photo"] = cached

    uncached = [n for n in set(bat_names) if n and n not in _photo_cache]
    if uncached: fetch_photos_async(uncached)

    return data
