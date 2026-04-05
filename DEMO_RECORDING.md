# Circuit Weaver MVP Demo Recording Guide

**Goal:** Create a 20-50 second video showing the end-user experience of the design-to-fab workflow for website/marketing.

---

## Option 1: Interactive Web Demo (Recommended)

### Setup
```bash
# Terminal 1: Start demo server
cd kicad_automations
py demo_server.py
# Output: [*] Circuit Weaver Demo Server
#         [*] http://localhost:8090
```

### Recording Steps
1. **Open browser:** Navigate to `http://localhost:8090`
2. **Start recording** (Chrome/Firefox DevTools or OBS)
3. **Click through workflow** (30 seconds):
   - Step 1: Show YAML (read description, 3 seconds)
   - Step 2: Click "Run Validation" → show result (5 seconds)
   - Step 3: Show generated files (3 seconds)
   - Step 4: Show design report excerpt (5 seconds)
   - Step 5: Show JLCPCB export (3 seconds)
   - Step 6: Show summary (5 seconds)
4. **Stop recording**

### Output
- File: `circuit_weaver_demo.mp4` (1920x1080, 30fps, H.264)
- Duration: 30-40 seconds
- Highlights: Automated validation, schematic generation, manufacturing export

### Tools
- **Chrome DevTools:** F12 → Sources → Recorder (native)
- **Firefox:** Built-in screenshot tool
- **OBS Studio:** obs.obsproject.com (free, professional)

---

## Option 2: Terminal Demo (Alternative)

### Setup
```bash
# Single command: run full workflow
cd kicad_automations
bash demo_cli.sh
```

### Recording Steps
1. **Record terminal window** with OBS or ffmpeg:
   ```bash
   # ffmpeg (Windows)
   ffmpeg -f gdigrab -i desktop -t 45 -c:v libx264 demo.mp4
   
   # OBS (recommended)
   # Settings → Output → Video Bitrate: 5000-8000 kbps
   ```
2. **Run the CLI demo** in recorded terminal
3. **Output shows:**
   - YAML spec (read first 20 lines)
   - Validation results (pass/warn summary)
   - Generated files list
   - Design report excerpt
   - BOM/CPL for JLCPCB
   - Timeline: ~30 seconds total

### Output
- File: `circuit_weaver_cli_demo.mp4` (1920x1080, 30fps)
- Duration: 35-45 seconds
- Highlights: CLI commands, real output, actual files generated

---

## Option 3: Hybrid (UI + CLI)

### Recording Steps
1. **0-15s:** Web demo (http://localhost:8090)
   - Show YAML, run validation, see results
2. **15-30s:** Terminal (bash demo_cli.sh)
   - Show actual CLI commands and file generation
3. **30-45s:** Back to web demo
   - Show summary and ready-to-order state

### Tools
- ffmpeg for screen capture
- OBS for multi-source composition
- DaVinci Resolve for editing (free)

---

## Technical Specifications

### Video Codec
- Container: MP4 (.mp4)
- Video Codec: H.264 (libx264)
- Resolution: 1920×1080 (1080p) or 1280×720 (720p)
- Frame Rate: 30 fps
- Bitrate: 2500-5000 kbps
- Duration: 30-50 seconds

### Audio (Optional)
- Background music: Optional (royalty-free)
- Narration: Optional (text overlay + music recommended)
- Ambient sound: Disable (terminal/browser only)

### File Size
- 1080p, 40 seconds, 3500 kbps: ~17 MB
- 720p, 40 seconds, 2000 kbps: ~10 MB

---

## Recording Checklist

- [ ] Demo server running (localhost:8090) or terminal ready
- [ ] Recording software installed (OBS, ffmpeg, or browser DevTools)
- [ ] Screen at 1920×1080 resolution
- [ ] Browser/terminal window maximized
- [ ] No notifications/popups visible
- [ ] Clean desktop background
- [ ] Recording started before user interaction
- [ ] Enough free disk space (~100 MB)

---

## Post-Recording (Editing)

### Using OBS
1. Source → Audio Device: Mute
2. Settings → Output → Recording
   - Format: MP4
   - Encoder: NVIDIA/AMD (hardware) or x264 (software)
   - Bitrate: 3000-5000 kbps
   - Rate Control: VBR or CBR

### Using ffmpeg (Lossless → Compressed)
```bash
# Capture desktop
ffmpeg -f gdigrab -i desktop -t 45 -c:v libx264 -crf 23 demo_raw.mp4

# Compress for web
ffmpeg -i demo_raw.mp4 -c:v libx264 -crf 28 -preset medium -c:a aac -b:a 128k circuit_weaver_demo.mp4
```

### Using DaVinci Resolve (Free)
1. Import raw video
2. Trim to 30-50 seconds
3. Add title card (2-3 seconds): "Circuit Weaver MVP"
4. Add lower-third text (throughout): Command names, file counts
5. Add background music (optional)
6. Export: YouTube 1080p preset

---

## Website Embedding

### HTML Embed
```html
<video width="100%" height="auto" controls style="max-width: 800px; margin: 20px auto; border-radius: 8px;">
  <source src="/videos/circuit_weaver_demo.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>
```

### Markdown
```markdown
[![Circuit Weaver MVP Demo](demo_thumbnail.jpg)](circuit_weaver_demo.mp4)
```

### GIF (Static Preview)
```bash
# Convert video to animated GIF
ffmpeg -i circuit_weaver_demo.mp4 -vf "fps=10,scale=800:-1" -c:v pam -f image2pipe - | convert -delay 10 - circuit_weaver_demo.gif

# Optimize GIF size
gifsicle --optimize=3 -o demo_optimized.gif demo.gif
```

---

## Marketing Copy (30-second callout)

**Video Callout (show on website):**
> "Design to JLCPCB order in 30 seconds. Write YAML, validate, generate schematic, export BOM — no manual CSV editing."

**Upper Left Text:** "Define YAML"  
**Upper Right Text:** "Validate ✓"  
**Lower Left Text:** "Generate Schematic"  
**Lower Right Text:** "Ready for Fab"

---

## Testing Before Posting

1. **Browser compatibility:** Test on Chrome, Firefox, Safari
2. **Mobile:** Ensure video is responsive at 375px width
3. **Performance:** Check video loading time (<2s), no buffering
4. **Accessibility:** Add captions (even if silent)
5. **Bandwidth:** Test on 4G connection

---

## Recommended Setup

### Easiest (Browser + OBS)
1. Open http://localhost:8090
2. Start OBS recording
3. Click through workflow (40 seconds)
4. Save as MP4

### Most Professional (Edited Video)
1. Record web demo (30 seconds)
2. Record CLI demo (30 seconds)
3. Edit in DaVinci Resolve
4. Add title, text overlays, background music
5. Export 1080p H.264

### For Website (Optimized)
- Format: MP4 (H.264, AAC audio)
- Resolution: 1280×720 or 1920×1080
- Bitrate: 2500-4000 kbps
- Duration: 30-50 seconds
- File size: <20 MB

---

## Quick Start Commands

```bash
# Terminal 1: Start server
cd circuit_weaver
py demo_server.py

# Terminal 2: Run CLI demo (for recording)
cd circuit_weaver
bash demo_cli.sh

# Screen record with ffmpeg (Windows)
ffmpeg -f gdigrab -i desktop -t 45 -c:v libx264 -crf 28 circuit_weaver_demo.mp4

# Compress for web
ffmpeg -i circuit_weaver_demo.mp4 -c:v libx264 -crf 28 -preset fast circuit_weaver_demo_web.mp4
```

---

## Files Included

- `demo_server.py` — Interactive web demo (localhost:8090)
- `demo_cli.sh` — Terminal workflow demo (~30 seconds)
- `record_demo.sh` — Recording instructions and setup
- `DEMO_RECORDING.md` — This file

## Ready?

1. Choose your recording method (web/terminal/hybrid)
2. Prepare your setup (server/terminal ready)
3. Start recording
4. Run through workflow
5. Save as MP4
6. Post to website/YouTube

**Estimated time:** 15-30 minutes from start to finished video.

