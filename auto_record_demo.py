#!/usr/bin/env python3
"""
Automated Circuit Weaver MVP demo recording.
Records 40-second video of web demo workflow: Define → Validate → Generate → Review → Export

Requirements:
  pip install mss opencv-python selenium pillow

Usage:
  py auto_record_demo.py [--output circuit_weaver_demo.mp4] [--fps 30]
"""

import argparse
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

try:
    import cv2
    import mss
    import numpy as np
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError as e:
    print(f"[!] Missing required package: {e}")
    print("[*] Install with: pip install mss opencv-python selenium pillow")
    exit(1)


class DemoRecorder:
    def __init__(self, output_file="circuit_weaver_demo.mp4", fps=30, resolution=(1920, 1080)):
        self.output_file = output_file
        self.fps = fps
        self.width, self.height = resolution
        self.recording = False
        self.frames = deque(maxlen=fps * 60)  # Max 60 seconds
        self.frame_count = 0

    def capture_screen(self):
        """Continuously capture screen frames."""
        print(f"[*] Starting screen capture ({self.width}x{self.height} @ {self.fps} fps)")

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor

            while self.recording:
                start = time.time()

                # Capture screen
                screenshot = sct.grab(monitor)
                frame = np.array(screenshot)

                # Convert BGRA to BGR (drop alpha channel)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                # Resize to target resolution if needed
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))

                self.frames.append(frame)
                self.frame_count += 1

                # Maintain FPS
                elapsed = time.time() - start
                sleep_time = max(0, (1.0 / self.fps) - elapsed)
                time.sleep(sleep_time)

    def automate_demo(self):
        """Automate web browser through demo workflow."""
        print("[*] Starting browser automation...")

        # Chrome options for headless (optional)
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless")  # Comment out to see browser
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        options.add_argument("--window-size=1920,1080")

        try:
            driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"[!] Chrome driver not found: {e}")
            print("[*] Install: pip install selenium webdriver-manager")
            print("[*] Or download from: chromedriver.chromium.org")
            return False

        try:
            driver.get("http://localhost:8090")
            wait = WebDriverWait(driver, 10)

            print("[*] Opened demo page, starting workflow automation...")
            time.sleep(2)  # Let page fully load

            # Step 1: Show YAML (5 seconds)
            print("[*] Step 1: Showing YAML definition")
            time.sleep(5)

            # Step 2: Click Validate button
            print("[*] Step 2: Running validation")
            self._click_step(driver, 2)
            time.sleep(1)

            # Find and click "Run Validation" button
            try:
                validate_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Run Validation')]"))
                )
                validate_btn.click()
                time.sleep(5)  # Wait for validation to complete
            except Exception as e:
                print(f"[!] Could not click validation button: {e}")

            # Step 3: Show Generate
            print("[*] Step 3: Showing generated files")
            self._click_step(driver, 3)
            time.sleep(5)

            # Step 4: Show Review
            print("[*] Step 4: Showing design review")
            self._click_step(driver, 4)
            time.sleep(5)

            # Step 5: Show Export
            print("[*] Step 5: Showing JLCPCB export")
            self._click_step(driver, 5)
            time.sleep(5)

            # Step 6: Show Ready
            print("[*] Step 6: Showing ready-to-order state")
            self._click_step(driver, 6)
            time.sleep(5)

            print("[*] Demo automation complete")
            return True

        finally:
            driver.quit()

    def _click_step(self, driver, step_num):
        """Click a workflow step."""
        try:
            steps = driver.find_elements(By.CLASS_NAME, "step")
            if step_num - 1 < len(steps):
                steps[step_num - 1].click()
                time.sleep(0.5)
        except Exception as e:
            print(f"[!] Could not click step {step_num}: {e}")

    def record(self, duration=40):
        """Record demo for specified duration."""
        print(f"[*] Recording for {duration} seconds...")

        self.recording = True

        # Start screen capture in background thread
        capture_thread = threading.Thread(target=self.capture_screen, daemon=True)
        capture_thread.start()

        time.sleep(1)  # Let capture start

        # Run demo automation
        automation_success = self.automate_demo()

        # Wait for specified duration
        elapsed = 0
        while elapsed < duration and self.recording:
            elapsed += 1
            time.sleep(1)
            print(f"  [{elapsed}/{duration}s] Captured {len(self.frames)} frames", end="\r")

        self.recording = False
        print(f"\n[+] Recording complete: {len(self.frames)} frames captured")

        return True

    def encode_video(self):
        """Encode captured frames to MP4."""
        if not self.frames:
            print("[!] No frames captured")
            return False

        print(f"[*] Encoding video to {self.output_file}...")

        # Use OpenCV to write video
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(self.output_file, fourcc, self.fps, (self.width, self.height))

        frame_count = 0
        for frame in self.frames:
            out.write(frame)
            frame_count += 1
            if frame_count % 30 == 0:
                print(f"  Encoding: {frame_count}/{len(self.frames)} frames", end="\r")

        out.release()
        print(f"\n[+] Video encoded: {self.output_file}")

        # Get file size
        file_size = Path(self.output_file).stat().st_size / (1024 * 1024)  # MB
        duration = len(self.frames) / self.fps
        print(f"[+] File size: {file_size:.1f} MB ({duration:.1f}s)")

        return True

    def compress_video(self):
        """Compress video for web using ffmpeg."""
        print("[*] Compressing video for web...")

        try:
            compressed_file = Path(self.output_file).stem + "_web.mp4"

            cmd = [
                "ffmpeg",
                "-i",
                self.output_file,
                "-c:v",
                "libx264",
                "-crf",
                "28",
                "-preset",
                "medium",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-y",  # Overwrite
                compressed_file,
            ]

            print(f"  Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                original_size = Path(self.output_file).stat().st_size / (1024 * 1024)
                compressed_size = Path(compressed_file).stat().st_size / (1024 * 1024)
                ratio = (1 - compressed_size / original_size) * 100

                print(f"[+] Compressed: {original_size:.1f} MB → {compressed_size:.1f} MB ({ratio:.0f}% smaller)")
                print(f"[+] Web version: {compressed_file}")
                return True
            else:
                print(f"[!] ffmpeg error: {result.stderr}")
                return False

        except FileNotFoundError:
            print("[!] ffmpeg not found. Install with: pip install ffmpeg-python")
            print("[!] Or download from: ffmpeg.org")
            return False


def main():
    parser = argparse.ArgumentParser(description="Automated Circuit Weaver MVP demo recording")
    parser.add_argument(
        "--output", "-o", default="circuit_weaver_demo.mp4", help="Output video file (default: circuit_weaver_demo.mp4)"
    )
    parser.add_argument("--fps", type=int, default=30, help="Frames per second (default: 30)")
    parser.add_argument("--duration", "-d", type=int, default=40, help="Recording duration in seconds (default: 40)")
    parser.add_argument("--compress", action="store_true", help="Compress video for web (requires ffmpeg)")
    parser.add_argument("--no-browser", action="store_true", help="Skip browser automation (manual testing)")

    args = parser.parse_args()

    print("=" * 60)
    print("  CIRCUIT WEAVER MVP — AUTOMATED DEMO RECORDING")
    print("=" * 60)
    print("")

    # Check dependencies
    print("[*] Checking dependencies...")
    deps = ["mss", "cv2", "selenium"]
    missing = []

    for dep in deps:
        try:
            __import__(dep if dep != "cv2" else "cv2")
            print(f"  [+] {dep}")
        except ImportError:
            print(f"  [!] {dep} - MISSING")
            missing.append(dep)

    if missing:
        print("\n[!] Install missing packages:")
        print(f"    pip install {' '.join(missing)}")
        return

    print("")

    # Ensure demo server is running
    print("[*] Checking demo server on localhost:8090...")
    try:
        import urllib.request

        urllib.request.urlopen("http://localhost:8090", timeout=2)
        print("  [+] Server is running")
    except Exception:
        print("  [!] Server not responding. Start it with:")
        print("      py demo_server.py")
        return

    print("")

    # Create recorder
    recorder = DemoRecorder(output_file=args.output, fps=args.fps, resolution=(1920, 1080))

    print("[*] Recording settings:")
    print(f"  Output: {args.output}")
    print(f"  FPS: {args.fps}")
    print(f"  Duration: {args.duration}s")
    print("  Resolution: 1920x1080")
    print("")

    # Record
    if args.no_browser:
        print("[*] Skipping browser automation (--no-browser flag)")
        print("[*] Manually click through the demo at http://localhost:8090")
        print("")
        recorder.recording = True
        capture_thread = threading.Thread(target=recorder.capture_screen, daemon=True)
        capture_thread.start()

        print("[*] Recording started... (press Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            recorder.recording = False
            print("\n[*] Recording stopped")
    else:
        recorder.record(duration=args.duration)

    # Encode
    if recorder.encode_video():
        # Optionally compress
        if args.compress:
            print("")
            recorder.compress_video()

        print("")
        print("=" * 60)
        print("  RECORDING COMPLETE")
        print("=" * 60)
        print(f"Video saved to: {Path(args.output).absolute()}")
        print("")
        print("Next steps:")
        print("  1. Review the video")
        print("  2. Upload to website or YouTube")
        print("  3. Embed in website with:")
        print(f'     <video controls><source src="{args.output}" type="video/mp4"></video>')
        print("")


if __name__ == "__main__":
    main()
