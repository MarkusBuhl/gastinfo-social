#!/usr/bin/env python3
"""
GASTiNFO.EU – Auto Social Media Scheduler
Runs every 3 days via GitHub Actions.
Schedules next 3 days of posts to Buffer.
Automatically selects seasonal content and event-specific posts.
"""

import os
import sys
import json
import math
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# ── Config ────────────────────────────────────────────────────────────────────
BUFFER_TOKEN  = os.environ["BUFFER_TOKEN"]
GITHUB_REPO   = os.environ.get("GITHUB_REPO",   "MarkusBuhl/gastinfo-social")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

VIENNA = ZoneInfo("Europe/Vienna")
DAYS_DE = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]

# ── Easter calculation (Gauss algorithm) ─────────────────────────────────────
def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)

# ── Season detection ──────────────────────────────────────────────────────────
def get_season(d: date) -> str:
    m = d.month
    if m in (12, 1, 2):  return "winter"
    if m in (3, 4, 5):   return "frühling"
    if m in (6, 7, 8):   return "sommer"
    return "herbst"

# ── Event matching ────────────────────────────────────────────────────────────
def get_active_event(d: date, events: list) -> dict | None:
    """Return highest-priority event active on date d, or None."""
    active = []
    for ev in events:
        if ev.get("easter_relative"):
            easter = easter_date(d.year)
            ev_start = easter - timedelta(days=ev["days_before"])
            ev_end   = easter + timedelta(days=ev["days_after"])
            if ev_start <= d <= ev_end:
                active.append(ev)
        elif ev.get("recurring_annually"):
            ms, ds = ev["month_start"], ev["day_start"]
            me, de = ev["month_end"],   ev["day_end"]
            start = date(d.year, ms, ds)
            # Handle year wrap (e.g. Silvester Dec 29 – Jan 2)
            if me < ms:
                end = date(d.year + 1, me, de)
                # also check previous year wrap
                if d < start:
                    start = date(d.year - 1, ms, ds)
                    end   = date(d.year,     me, de)
            else:
                end = date(d.year, me, de)
            if start <= d <= end:
                active.append(ev)
        else:
            # Fixed date range
            ev_start = date.fromisoformat(ev["start"])
            ev_end   = date.fromisoformat(ev["end"])
            if ev_start <= d <= ev_end:
                active.append(ev)

    if not active:
        return None
    return max(active, key=lambda e: e.get("priority", 0))

# ── Post selection ────────────────────────────────────────────────────────────
def select_post(d: date, library: dict) -> dict:
    """
    Priority:
    1. Active event post
    2. Seasonal override for this weekday
    3. Default weekday post
    """
    day_name = DAYS_DE[d.weekday()]
    season   = get_season(d)
    event    = get_active_event(d, library.get("events", []))

    if event:
        print(f"  → Event: {event['name']}")
        return {
            "instagram": event.get("instagram"),
            "facebook":  event.get("facebook"),
            "tiktok":    event.get("tiktok"),
        }

    seasonal = library.get("seasonal", {}).get(season, {}).get(day_name)
    if seasonal:
        print(f"  → Seasonal ({season}) override")
        return seasonal

    print(f"  → Default weekday post")
    return library["weekdays"][day_name]

# ── Video URL ─────────────────────────────────────────────────────────────────
def video_url(day_name: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/posts/{day_name}/slideshow_reel.mp4"
    )

# ── Buffer API ────────────────────────────────────────────────────────────────
def due_at_iso(posting_date: date, time_str: str) -> str:
    h, m = map(int, time_str.split(":"))
    dt = datetime(
        posting_date.year, posting_date.month, posting_date.day,
        h, m, 0, tzinfo=VIENNA
    )
    return dt.isoformat()

def create_buffer_post(channel_id: str, text: str, video: str,
                       due_at: str, platform: str) -> dict:
    """Schedule a post via Buffer MCP server (same as Cowork integration)."""
    if platform == "instagram":
        metadata = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    elif platform == "facebook":
        metadata = {"facebook": {"type": "reel"}}
    else:
        metadata = {}

    headers = {
        "Authorization": f"Bearer {BUFFER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "create_post",
            "arguments": {
                "channelId":      channel_id,
                "text":           text,
                "schedulingType": "automatic",
                "mode":           "customScheduled",
                "dueAt":          due_at,
                "assets":         [{"video": {"url": video}}],
                "metadata":       metadata,
            }
        }
    }

    r = requests.post(
        "https://mcp.buffer.com/mcp",
        headers=headers,
        json=payload,
        timeout=30
    )

    # Handle SSE response (Buffer MCP uses text/event-stream)
    result_text = ""
    if "text/event-stream" in r.headers.get("Content-Type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                result_text = line[5:].strip()
    else:
        result_text = r.text

    try:
        data = json.loads(result_text) if result_text else r.json()
    except Exception:
        data = {"raw": r.text}

    # Check for errors in MCP response
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")

    # Extract post ID from MCP result content
    result = data.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list):
        post_data_str = content[0].get("text", "{}")
        try:
            return json.loads(post_data_str)
        except Exception:
            return {"status": "scheduled", "raw": post_data_str}

    return data

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    with open("posts_library.json", encoding="utf-8") as f:
        library = json.load(f)

    channels = library["channels"]

    today = date.today()
    days  = [today + timedelta(days=i) for i in range(3)]

    print(f"Scheduling posts for: {', '.join(str(d) for d in days)}\n")

    results = []
    for d in days:
        day_name = DAYS_DE[d.weekday()]
        print(f"[{d} {day_name}]")
        posts = select_post(d, library)

        for platform in ("instagram", "facebook", "tiktok"):
            post = posts.get(platform)
            if not post:
                continue
            channel_id = channels[platform]
            vid        = video_url(day_name)
            due        = due_at_iso(d, post["time"])
            try:
                result = create_buffer_post(
                    channel_id=channel_id,
                    text=post["caption"],
                    video=vid,
                    due_at=due,
                    platform=platform,
                )
                print(f"  ✓ {plat