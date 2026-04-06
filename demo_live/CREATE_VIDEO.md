# Creating a Video from the Demo Recording

This directory contains `demo.cast` — a terminal recording in asciinema format. Below are 3 ways to create a viewable video.

## Option 1: Host on asciinema.org (Easiest) ⭐

The `.cast` file is already in the correct format for asciinema.org, which provides free hosting + playback:

```bash
# Install asciinema (one-time)
pip install asciinema

# Upload your recording
cd demo_live
asciinema upload demo.cast
```

You'll get a shareable URL like: `https://asciinema.org/a/abc123def456`

**Pros:**
- ✅ Free hosting
- ✅ Video-like player with timeline
- ✅ Shareable URL
- ✅ Works immediately
- ✅ Full interactive controls

**Embed in README:**
```html
<script id="asciicast-abc123def456" src="https://asciinema.org/a/abc123def456.js" async></script>
```

---

## Option 2: Self-Hosted HTML Player

We provide `index.html` which plays the `.cast` file locally:

```bash
# Copy to your web server
cp index.html demo.cast /var/www/html/demo/

# Access at: https://yourdomain.com/demo/index.html
```

**Pros:**
- ✅ Full control over hosting
- ✅ No external dependencies
- ✅ Works offline after initial load
- ✅ Dark theme, mobile-friendly

---

## Option 3: Generate MP4 Video

To create an actual `.mp4` file:

### Windows (via scoop):
```bash
scoop install ffmpeg
py generate_demo_video.py demo.cast -o demo.mp4
```

### macOS (via Homebrew):
```bash
brew install ffmpeg
python generate_demo_video.py demo.cast -o demo.mp4
```

### Linux (apt):
```bash
sudo apt install ffmpeg
python3 generate_demo_video.py demo.cast -o demo.mp4
```

**Note:** The Python script requires:
- `ffmpeg` in PATH
- `pillow` (auto-installed if missing)

---

## Recommended: Use Option 1 (asciinema.org)

Here's why it's the best for GitHub:

1. **Works on GitHub** — asciinema embeds work in GitHub markdown
2. **No setup** — No ffmpeg, no local hosting needed
3. **Interactive** — Users can play/pause/seek and copy text
4. **Permanent URL** — Shareable link that never changes
5. **Free** — No cost, no limits

**Steps:**
```bash
pip install asciinema
cd demo_live
asciinema upload demo.cast
# Copy the returned URL into your README
```

---

## Files

- `demo.cast` (5.6 KB) — Terminal recording (asciinema v2 format)
- `index.html` (14 KB) — Self-hosted web player
- `generate_demo_video.py` — Script to create MP4 (requires ffmpeg)

---

## Update README After Getting URL

Once you have your video URL from asciinema.org:

```markdown
## 🎬 Live Demo

[**Watch on asciinema.org →**](https://asciinema.org/a/YOUR_ID)

Or [view the walkthrough](DEMO_WALKTHROUGH.md)
```

Done!
