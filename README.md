# Sports Adda67 — Cricket Overlay v15

## What's New in v15
- **Sweep effect**: 4 passes per cycle (was 1), half intensity, multi-color (not just white)
- **Background hue-loop**: Slowed to 28s (was 14s) — half speed
- **Flag**: Circular with rainbow rotating ring outside
- **Cricket ball**: Shifted up to roll on player face area
- **This Over + Last Over**: Single horizontal line, 1.5× size balls
- **Team score auto-update**: Fixed — updates from live data every 2s
- **Flag auto-update**: Fixed — auto-updates from data.json flag_img field
- **H2H on click**: Click LEFT team flag → Head to Head stats (Cricbuzz scraping)
- **Venue+Weather on click**: Click RIGHT team flag → Venue stats + live weather
- **Playing XI**: Scraped from Cricbuzz squad URL automatically
- **Player detail**: Click any player card → full stats + career info from Cricbuzz
- **All data real**: No mock data — everything scraped from Cricbuzz/Crex in real-time

## Deployment (Railway / Render)

1. Upload this folder
2. Set start command: `python app.py`
3. Open: `https://your-app.url/overlay?match=MATCH_ID&squad=SQUAD_URL`

## Match ID
From cricbuzz.com URL: `https://www.cricbuzz.com/live-cricket-scores/12345/...`

## Squad URL (for Playing XI)
From cricbuzz.com: `https://www.cricbuzz.com/cricket-match-squads/12345/match-name`

## OBS Setup
Browser Source → paste overlay URL → 1280×720 → Transparent background

## Keyboard Shortcuts
- `Ctrl+S` → Open Admin panel
- `Esc` → Close all modals

## Click Actions
- Left team flag → Head to Head stats
- Right team flag → Venue stats + Weather
- Player card → Player details + career stats
- Playing XI flag → Opens Playing XI screen
