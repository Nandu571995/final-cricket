#!/usr/bin/env python3
"""
Run this on your Railway server (or locally):
  python3 diagnose.py 139472

It will tell you EXACTLY what is broken.
"""
import sys, json, re, requests, time

match_id = sys.argv[1] if len(sys.argv) > 1 else "139472"
BASE = f"http://localhost:{__import__('os').environ.get('PORT','8000')}"

HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cricbuzz.com/",
    "x-cricbuzz-client": "app",
    "x-app-version": "6.06",
}
HEADERS_MOB = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

sep = lambda: print("-"*60)

print(f"\n{'='*60}")
print(f"  CRICKET OVERLAY DIAGNOSTIC — match {match_id}")
print(f"{'='*60}\n")

# ── TEST 1: Cricbuzz JSON API ─────────────────────────────────────
sep()
print("TEST 1: Cricbuzz JSON API (primary data source)")
for path in [
    f"https://www.cricbuzz.com/api/cricket-match/{match_id}/mini-scorecard",
    f"https://www.cricbuzz.com/api/cricket-match/{match_id}/live-score",
]:
    try:
        r = requests.get(path, headers=HEADERS_API, timeout=8)
        print(f"  {r.status_code} {path}")
        if r.status_code == 200:
            d = r.json()
            ms = d.get("miniscore") or {}
            msd = d.get("matchScoreDetails") or {}
            mhdr = d.get("matchHeader") or {}
            innings = msd.get("inningsScoreList") or []
            print(f"    matchHeader.status : {mhdr.get('status','')}")
            print(f"    innings count      : {len(innings)}")
            for inn in innings:
                print(f"      {inn.get('batTeamName','?')} {inn.get('score','?')}/{inn.get('wickets','?')} ({inn.get('overs','?')})")
            print(f"    CRR                : {ms.get('currentRunRate','?')}")
            bat = ms.get("batsmanStriker") or {}
            print(f"    batsmanStriker     : {bat.get('batName','?')} {bat.get('batRuns','?')}({bat.get('batBalls','?')})")
            bowl = ms.get("bowlerStriker") or {}
            print(f"    bowlerStriker      : {bowl.get('bowlName','?')} {bowl.get('bowlWkts','?')}-{bowl.get('bowlRuns','?')} ({bowl.get('bowlOvs','?')})")
        else:
            print(f"    FAILED: HTTP {r.status_code}")
            print(f"    Response: {r.text[:200]}")
    except Exception as e:
        print(f"  ERROR: {e}")

# ── TEST 2: Cricbuzz HTML page ────────────────────────────────────
sep()
print("TEST 2: Cricbuzz HTML page (fallback)")
try:
    url = f"https://m.cricbuzz.com/cricket-commentary/{match_id}"
    r = requests.get(url, headers=HEADERS_MOB, timeout=10)
    print(f"  Status: {r.status_code}")
    html = r.text
    print(f"  Size: {len(html)} bytes")
    has_crr = "currentRunRate" in html
    has_batsman = "batsmanStriker" in html or "batName" in html
    print(f"  Has currentRunRate : {has_crr}")
    print(f"  Has batsmanStriker : {has_batsman}")
    if has_crr:
        m = re.search(r'"currentRunRate"\s*:\s*([\d.]+)', html)
        print(f"  CRR value          : {m.group(1) if m else 'regex failed'}")
    if has_batsman:
        m = re.search(r'"batName"\s*:\s*"([^"]+)"', html)
        print(f"  batName            : {m.group(1) if m else 'regex failed'}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── TEST 3: Your /data endpoint ───────────────────────────────────
sep()
print(f"TEST 3: Your server /data/{match_id}")
try:
    r = requests.get(f"{BASE}/data/{match_id}", timeout=5)
    print(f"  Status: {r.status_code}")
    d = r.json()
    print(f"  team1.name  : '{d.get('team1',{}).get('name','')}'")
    print(f"  team1.score : '{d.get('team1',{}).get('score','')}'")
    print(f"  team2.name  : '{d.get('team2',{}).get('name','')}'")
    print(f"  crr         : '{d.get('crr','')}'")
    b1 = d.get('batsman1',{})
    print(f"  batsman1    : '{b1.get('name','')}' {b1.get('runs','?')}({b1.get('balls','?')})")
    bw = d.get('bowler',{})
    print(f"  bowler      : '{bw.get('name','')}' {bw.get('wickets','?')}-{bw.get('runs','?')}")
    print(f"  last_updated: '{d.get('last_updated','')}'")
    
    print("\n  [Checking if data actually updates — waiting 5s...]")
    time.sleep(5)
    r2 = requests.get(f"{BASE}/data/{match_id}", timeout=5)
    d2 = r2.json()
    same = d2.get('last_updated') == d.get('last_updated')
    print(f"  last_updated after 5s: '{d2.get('last_updated','')}' {'(SAME - NOT UPDATING!)' if same else '(CHANGED - updating OK)'}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── TEST 4: /status ───────────────────────────────────────────────
sep()
print("TEST 4: Your server /status")
try:
    r = requests.get(f"{BASE}/status", timeout=5)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:500]}")
except Exception as e:
    print(f"  ERROR: {e}")

sep()
print("\nPaste the output above and we'll know exactly what to fix.\n")
