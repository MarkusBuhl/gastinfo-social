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
    """Schedule a post via Buffer v1 REST API."""
    metadata = {}
    if platform == "instagram":
        metadata = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    elif platform == "facebook":
        metadata = {"facebook": {"type": "reel"}}

    # Try newer Buffer API (MCP-compatible)
    headers = {
        "Authorization": f"Bearer {BUFFER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "channelId":      channel_id,
        "text":           text,
        "schedulingType": "automatic",
        "mode":           "customScheduled",
        "dueAt":          due_at,
        "assets":         [{"video": {"url": video}}],
        "metadata":       metadata,
    }
    # Attempt newer API first
    for url in [
        "https://api.bufferapp.com/1/updates/create.json",
    ]:
        try:
            # v1 API uses form-encoded with access_token param
            form = {
                "access_token":   BUFFER_TOKEN,
                "profile_ids[]":  channel_id,
                "text":           text,
                "scheduled_at":   due_at,
                "media[video]":   video,
            }
            r = requests.post(url, data=form, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("success") or data.get("id"):
                return data
        except Exception as e:
            print(f"    API attempt failed ({url}): {e}", file=sys.stderr)

    raise RuntimeError("All Buffer API attempts failed")

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
                print(f"  ✓ {platform:10s} {post['time']}  →  scheduled")
                results.append({"day": day_name, "platform": platform, "ok": True})
            except Exception as e:
                print(f"  ✗ {platform:10s}: {e}", file=sys.stderr)
                results.append({"day": day_name, "platform": platform, "ok": False})
        print()

    ok    = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"Done: {ok}/{total} posts scheduled.")
    if ok < total:
        sys.exit(1)  # Fail the GitHub Action if any post failed

if __name__ == "__main__":
    main()
