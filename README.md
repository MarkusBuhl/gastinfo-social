# GASTiNFO.EU – Auto Social Media Scheduler

Automatically schedules Instagram, Facebook and TikTok posts every 3 days via GitHub Actions.
No PC needed — runs entirely in the cloud.

---

## One-time Setup (15 minutes)

### 1. Create GitHub Repository

1. Go to https://github.com/new
2. Name: `gastinfo-social`
3. Set to **Public** (required for raw video URLs)
4. Click **Create repository**

### 2. Copy Videos into This Folder

Copy the 7 MP4 files into the `posts/` subfolders:

```
posts/
├── Montag/slideshow_reel.mp4
├── Dienstag/slideshow_reel.mp4
├── Mittwoch/slideshow_reel.mp4
├── Donnerstag/slideshow_reel.mp4
├── Freitag/slideshow_reel.mp4
├── Samstag/slideshow_reel.mp4
└── Sonntag/slideshow_reel.mp4
```

Source files are at:
`C:\Users\PC\Documents\Developement\Projekte\GASTiNFO\SocilMediaAssets\posts\[Tag]\slideshow_reel.mp4`

### 3. Push to GitHub

Open a terminal in this folder (`github_action/`) and run:

```bash
git init
git add .
git commit -m "Initial setup"
git branch -M main
git remote add origin https://github.com/MarkusBuhl/gastinfo-social.git
git push -u origin main
```

### 4. Add Buffer Secret

1. Go to your repo on GitHub
2. **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `BUFFER_TOKEN`
5. Value: `f7pmsDttnjCJiXL6exfRXIZzLBsa9i-TUF5sBHoHk8l`
6. Click **Add secret**

### 5. Test Run

1. Go to **Actions** tab in your GitHub repo
2. Click **Auto Schedule Posts**
3. Click **Run workflow** → **Run workflow**
4. Check the log output — should show ✓ for each post

---

## How It Works

- Runs automatically every 3 days at 20:00 Vienna time
- Schedules the **next 3 days** of posts (IG + FB + TikTok = 9 posts per run)
- Fits within Buffer's free plan limit of 10 scheduled posts

### Smart Content Selection (priority order):

1. **Events** — if an event is active, uses the event-specific post
2. **Seasonal** — adjusts content for summer/winter/spring/fall (no ski posts in summer!)
3. **Default** — standard weekday rotation

### Events included:
- FIFA WM 2026 (June 11 – July 19, 2026)
- Weihnachten (Dec 22–26, annually)
- Silvester (Dec 29 – Jan 2, annually)
- Ostern (5 days before to 2 days after Easter Sunday, annually)
- Valentinstag (Feb 12–15, annually)

### Seasons:
- **Winter** (Dez–Feb): Ski/snow content for mountain hosts
- **Frühling** (Mär–Mai): Hiking, cycling, spring events
- **Sommer** (Jun–Aug): Pool, BBQ, lakes, no ski content
- **Herbst** (Sep–Nov): Wine harvest, hiking in autumn colours

---

## Adding New Events

Edit `posts_library.json` → `events` array. Add a new object:

```json
{
  "name": "Your Event",
  "start": "2027-03-15",
  "end": "2027-03-20",
  "priority": 8,
  "instagram": {"caption": "...", "time": "19:00"},
  "facebook":  {"caption": "...", "time": "20:00"},
  "tiktok":    {"caption": "...", "time": "20:30"}
}
```

## Adding New Videos

Add seasonal or event-specific videos to `posts/` subfolders, then update the `video_url()` function in `schedule.py` to point to the right file.

---

## Troubleshooting

- **Posts not appearing in Buffer**: Check the GitHub Actions log (Actions tab → latest run)
- **Wrong time**: The scheduler uses Vienna/CEST timezone automatically
- **Buffer limit reached**: Posts from previous days will publish and free up slots before the next run
