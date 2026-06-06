#!/usr/bin/env python3
"""
GASTiNFO.EU - Auto Social Media Scheduler
Runs every 3 days via GitHub Actions.
Schedules next 3 days of posts to Buffer.
Automatically selects seasonal content and event-specific posts.
"""

import os
import sys
import json
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
def easter_date(year):
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
def get_season(d):
    m = d.month
    if m in (12, 1, 2):  return "winter"
    if m in (3, 4, 5):   return "fruehling"
    if m in (6, 7, 8):   return "sommer"
    return "herbst"

# ── Event matching ────────────────────────────────────────────────────────────
def get_active_event(d, events):
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
            if me < ms:
                end = date(d.year + 1, me, de)
                if d < start:
                    start = date(d.year - 1, ms, ds)
                    end   = date(d.year,     me, de)
            else:
                end = date(d.year, me, de)
            if start <= d <= end:
                active.append(ev)
        else:
            ev_start = date.fromisoformat(ev["start"])
            ev_end   = date.fromisoformat(ev["end"])
            if ev_start <= d <= ev_end:
                active.append(ev)

    if not active:
        return None
    return max(active, key=lambda e: e.get("priority", 0))

# ── Post selection ────────────────────────────────────────────────────────────
def select_post(d, library):
    day_name = DAYS_DE[d.weekday()]
    season   = get_season(d)
    event    = get_active_event(d, library.get("events", []))

    if event:
        print(f"  -> Event: {event['name']}")
        return {
            "instagram": event.get("instagram"),
            "facebook":  event.get("facebook"),
            "tiktok":    event.get("tiktok"),
        }

    # Map JSON season keys (frühling uses ascii key in JSON)
    season_key = "frühling" if season == "fruehling" else season
    seasonal = library.get("seasonal", {}).get(season_key, {}).get(day_name)
    if seasonal:
        print(f"  -> Seasonal ({season_key}) override")
        return seasonal

    print(f"  -> Default weekday post")
    return library["weekdays"][day_name]

# ── Video URL ─────────────────────────────────────────────────────────────────
def video_url(day_name):
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/posts/{day_name}/slideshow_reel.mp4"
    )

# ── Buffer API via MCP server ─────────────────────────────────────────────────
def due_at_iso(posting_date, time_str):
    h, m = map(int, time_str.split(":"))
    dt = datetime(
        posting_date.year, posting_date.month, posting_date.day,
        h, m, 0, tzinfo=VIENNA
    )
    return dt.isoformat()

def create_buffer_post(channel_id, text, video, due_at, platform):
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

    # Handle SSE response
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

    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")

    result = data.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list):
        post_data_str = content[0].get("text", "{}")
        try:
            return json.loads(post_data_str)
        except Exception:
            return {"status": "scheduled", "raw": post_data_str}

    return data

# ── Fetch existing scheduled posts (duplicate check) ──────────────────────────
def get_existing_scheduled(org_id, start_iso, end_iso):
    """Returns a set of (channelId, dueAt_minute) for already scheduled posts."""
    headers = {
        "Authorization": f"Bearer {BUFFER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "list_posts",
            "arguments": {
                "organizationId": org_id,
                "status": ["scheduled"],
                "dueAt": {"start": start_iso, "end": end_iso},
                "first": 100,
            }
        }
    }
    try:
        r = requests.post(
            "https://mcp.buffer.com/mcp",
            headers=headers,
            json=payload,
            timeout=30
        )
        result_text = ""
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    result_text = line[5:].strip()
        else:
            result_text = r.text

        data = json.loads(result_text) if result_text else r.json()
        content = data.get("result", {}).get("content", [])
        if content:
            posts_data = json.loads(content[0].get("text", "{}"))
            edges = posts_data.get("edges", [])
            # Return set of (channelId, dueAt truncated to minute)
            return {
                (e["node"]["channelId"], e["node"]["dueAt"][:16])
                for e in edges
            }
    except Exception as ex:
        print(f"  WARNING: Could not fetch existing posts for duplicate check: {ex}", file=sys.stderr)
    return set()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Load post library
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "posts_library.json"), encoding="utf-8") as f:
        library = json.load(f)

    channels  = library["channels"]
    org_id    = "6a211817de506bce5254d906"
    today     = datetime.now(VIENNA).date()
    days_ahead = 3  # schedule next 3 days (script runs every 3 days)

    # Fetch already-scheduled posts for the window we're about to schedule
    window_start = datetime(today.year, today.month, today.day, 0, 0, tzinfo=VIENNA).isoformat()
    window_end   = datetime(
        (today + timedelta(days=days_ahead)).year,
        (today + timedelta(days=days_ahead)).month,
        (today + timedelta(days=days_ahead)).day,
        23, 59, tzinfo=VIENNA
    ).isoformat()

    existing = get_existing_scheduled(org_id, window_start, window_end)
    # Normalize to (channelId, date-string) for day-level duplicate check
    existing_days = {(ch, due[:10]) for ch, due in existing}

    print(f"Already scheduled in window: {len(existing_days)} channel-days")

    scheduled_count = 0

    for offset in range(days_ahead):
        post_date = today + timedelta(days=offset)
        day_name  = DAYS_DE[post_date.weekday()]
        post      = select_post(post_date, library)

        print(f"\n{post_date} ({day_name}):")

        for platform in ("instagram", "facebook", "tiktok"):
            channel_id = channels[platform]
            content    = post.get(platform)
            if not content:
                print(f"  {platform}: no content, skipping")
                continue

            date_str = post_date.isoformat()
            if (channel_id, date_str) in existing_days:
                print(f"  {platform}: already scheduled, skipping")
                continue

            caption  = content.get("caption", "")
            time_str = content.get("time", "12:00")
            due_at   = due_at_iso(post_date, time_str)
            vid      = video_url(day_name)

            try:
                result = create_buffer_post(channel_id, caption, vid, due_at, platform)
                print(f"  {platform}: scheduled for {due_at} ✓")
                scheduled_count += 1
            except Exception as ex:
                print(f"  {platform}: ERROR – {ex}", file=sys.stderr)

    print(f"\nDone. {scheduled_count} new post(s) scheduled.")

if __name__ == "__main__":
    main()