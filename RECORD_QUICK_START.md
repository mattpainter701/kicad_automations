# Automated Demo Recording — Quick Start

Record a professional 40-second demo video **fully automatically** with one command.

---

## Prerequisites

1. **Python 3.10+** (already have)
2. **Chrome/Chromium browser** (system-installed)
3. **FFmpeg** (optional, for compression)

---

## Installation (1 minute)

```bash
# Install recording dependencies
pip install -r requirements-recording.txt

# Optional: For video compression
pip install ffmpeg-python
# Or download from: ffmpeg.org
```

---

## Recording (3 minutes)

### Step 1: Start the demo server
```bash
# Terminal 1
py demo_server.py
# Output: [*] Circuit Weaver Demo Server
#         [*] http://localhost:8090
```

### Step 2: Run the recorder
```bash
# Terminal 2 (in same directory)
py auto_record_demo.py
```

**That's it.** The script will:
- ✅ Capture your screen (1920×1080, 30fps)
- ✅ Open Chrome automatically
- ✅ Navigate to localhost:8090
- ✅ Click through all 6 workflow steps (fully automated)
- ✅ Record everything for 40 seconds
- ✅ Encode to MP4
- ✅ Save as `circuit_weaver_demo.mp4`

---

## Output

```
[*] Recording for 40 seconds...
[*] Starting browser automation...
[*] Opened demo page, starting workflow automation...
[*] Step 1: Showing YAML definition
[*] Step 2: Running validation
[*] Step 3: Showing generated files
[*] Step 4: Showing design review
[*] Step 5: Showing JLCPCB export
[*] Step 6: Showing ready-to-order state
[*] Demo automation complete
[+] Recording complete: 1200 frames captured
[*] Encoding video to circuit_weaver_demo.mp4...
[+] Video encoded: circuit_weaver_demo.mp4
[+] File size: 45.3 MB (40.0s)
```

**File:** `circuit_weaver_demo.mp4` (45 MB, 1920×1080, 40 seconds)

---

## Compress for Web (Optional)

```bash
# Reduce file size ~70% (15 MB from 45 MB)
py auto_record_demo.py --compress

# Output: circuit_weaver_demo_web.mp4
```

---

## Advanced Options

```bash
# Custom output filename
py auto_record_demo.py --output my_demo.mp4

# Custom duration (30 seconds)
py auto_record_demo.py --duration 30

# Manual recording (you click through demo)
py auto_record_demo.py --no-browser
```

---

## Troubleshooting

### Chrome not found
```
[!] Chrome driver not found
```

**Solution:**
```bash
pip install webdriver-manager
```

The script will auto-download ChromeDriver matching your Chrome version.

### mss (screen capture) not found
```
[!] Missing required package: No module named 'mss'
```

**Solution:**
```bash
pip install mss opencv-python selenium
```

### ffmpeg not found (for compression)
```
[!] ffmpeg not found
```

**Solution:** Download from [ffmpeg.org](https://ffmpeg.org/download.html) or:
```bash
pip install ffmpeg-python
```

### Demo server not responding
```
[!] Server not responding. Start it with: py demo_server.py
```

**Solution:** Open a second terminal and run:
```bash
py demo_server.py
```

---

## What Gets Recorded

1. **0-5s:** YAML specification (Define step)
2. **5-10s:** Validation running, results shown (Validate step)
3. **10-15s:** Generated files list (Generate step)
4. **15-20s:** Design report excerpt (Review step)
5. **20-25s:** JLCPCB export details (Export step)
6. **25-30s:** Ready-to-order summary (Ready step)
7. **30-40s:** Summary screen + return to start

---

## Website Embedding

After recording, embed the video:

```html
<video width="100%" height="auto" controls style="max-width: 900px; margin: 20px auto;">
  <source src="/videos/circuit_weaver_demo.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>
```

Or for responsive embedding:

```html
<div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 900px;">
  <video style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" controls>
    <source src="/videos/circuit_weaver_demo.mp4" type="video/mp4">
  </video>
</div>
```

---

## Performance Notes

- **Screen Capture:** Uses `mss` (very fast, ~0.5ms per frame)
- **Browser Automation:** Uses Selenium with explicit waits (stable, no timing issues)
- **Video Encoding:** Uses OpenCV H.264 encoder (~5-10 seconds)
- **Total Time:** ~60 seconds (40s recording + 10s automation + 10s encoding)

---

## One-Liner

```bash
py demo_server.py & sleep 2 && py auto_record_demo.py --compress
```

Run this and walk away. Your video will be ready in ~60 seconds.

---

## Next Steps

1. ✅ Run the recorder
2. ✅ Get `circuit_weaver_demo.mp4` (or `circuit_weaver_demo_web.mp4`)
3. ✅ Upload to website
4. ✅ Share on social media / YouTube

Done! 🎬
