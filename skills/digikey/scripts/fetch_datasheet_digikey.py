#!/usr/bin/env python3
"""Download a datasheet PDF from a manufacturer URL.

Handles manufacturer-specific quirks:
- TI: DigiKey returns JS-redirect URLs; this script extracts the direct PDF URL
- Protocol-relative URLs (//mm.digikey.com/...): adds https: prefix
- Microchip: Redirects to login; uses alternative URL patterns as fallback
- Various manufacturers that block bare urllib: uses requests library with
  proper User-Agent (handles HTTP/2, redirects, and anti-bot checks)

Usage:
    python3 fetch_datasheet_digikey.py <url> [--output <path>]
    python3 fetch_datasheet_digikey.py --search <MPN> [--output <path>]

The --search mode requires DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET
environment variables.

Dependencies:
    - requests (pip install requests) — preferred, handles all manufacturer sites
    - Falls back to urllib if requests is not installed (some sites may fail)

Exit codes:
    0 = success (PDF downloaded)
    1 = download failed after all attempts
    2 = search failed (API error or part not found)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

# Try to import optional dependencies; graceful fallback if not installed
try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError:
    _sync_playwright = None


def _friendly_filename(mpn: str, description: str = "") -> str:
    """Build a human-readable filename (no extension) from MPN + description."""
    def _sanitize(s):
        s = re.sub(r'[/\\:*?"<>|,;]', "_", s)
        s = re.sub(r"\s+", "_", s)
        return re.sub(r"_+", "_", s).strip("_")

    base = _sanitize(mpn)
    if not description:
        return base
    desc = description.strip()
    if len(desc) > 80:
        desc = desc[:77].rsplit(" ", 1)[0]
    desc = _sanitize(desc)
    return f"{base}_{desc}" if desc else base


def _get_digikey_token() -> str | None:
    """Get a DigiKey OAuth token, using a cached version if still valid.

    Caches the token to a temp file with a 9-minute TTL (tokens last 10 minutes).
    """
    import tempfile
    import time

    client_id = os.environ.get("DIGIKEY_CLIENT_ID", "")
    client_secret = os.environ.get("DIGIKEY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("Error: DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET required", file=sys.stderr)
        return None

    cache_path = os.path.join(tempfile.gettempdir(), "digikey_token_cache.json")

    # Check cache
    try:
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                cached = json.load(f)
            if (cached.get("client_id") == client_id
                    and cached.get("expires_at", 0) > time.time()):
                return cached["token"]
    except (json.JSONDecodeError, OSError):
        pass

    # Fetch new token
    try:
        token_data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }).encode()
        req = urllib.request.Request(
            "https://api.digikey.com/v1/oauth2/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_resp = json.loads(resp.read())
        token = token_resp.get("access_token", "")
        if not token:
            print("Error: Failed to get OAuth token", file=sys.stderr)
            return None

        # Cache with 9-minute TTL (token lasts 10 min, 1 min safety margin)
        try:
            with open(cache_path, "w") as f:
                json.dump({
                    "token": token,
                    "client_id": client_id,
                    "expires_at": time.time() + 540,
                }, f)
            os.chmod(cache_path, 0o600)
        except OSError:
            pass  # caching is best-effort

        return token
    except Exception as e:
        print(f"Error: OAuth failed: {e}", file=sys.stderr)
        return None


def search_digikey(mpn: str) -> dict | None:
    """Search DigiKey API for a part, return first match with datasheet URL."""
    client_id = os.environ.get("DIGIKEY_CLIENT_ID", "")
    token = _get_digikey_token()
    if not token:
        return None

    # Search for the part
    try:
        search_body = json.dumps({"Keywords": mpn, "Limit": 3}).encode()
        req = urllib.request.Request(
            "https://api.digikey.com/products/v4/search/keyword",
            data=search_body,
            headers={
                "Content-Type": "application/json",
                "X-DIGIKEY-Client-Id": client_id,
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Error: Search failed: {e}", file=sys.stderr)
        return None

    products = data.get("Products", [])
    if not products:
        print(f"No results for '{mpn}'", file=sys.stderr)
        return None

    # Prefer exact MPN match
    for p in products:
        if p.get("ManufacturerProductNumber", "").upper().startswith(mpn.upper()):
            return p
    return products[0]


def normalize_url(url: str) -> str:
    """Convert manufacturer-specific redirect URLs to direct PDF URLs.

    DigiKey's DatasheetUrl field often points to manufacturer redirect pages
    rather than direct PDFs. This function extracts the actual PDF URL.
    """
    # Protocol-relative URLs from DigiKey (//mm.digikey.com/...)
    if url.startswith("//"):
        url = "https:" + url

    # TI redirect: extract the gotoUrl parameter which contains the direct link
    if "ti.com/general/docs/suppproductinfo" in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        goto = params.get("gotoUrl", [""])[0]
        if goto:
            return goto

    # Microchip redirect: extract the actual URL from the redirect wrapper
    if "microchip.com/filehandler/redirect" in url.lower():
        idx = url.find("?")
        if idx >= 0:
            return url[idx + 1:]

    return url


def download_pdf(url: str, output_path: str) -> bool:
    """Download a PDF from a URL, trying multiple methods.

    Strategy:
    1. Try requests library (handles HTTP/2, redirects, all manufacturer sites)
    2. Fall back to Python urllib (HTTP/1.1 only — some sites may timeout)

    Returns True if a valid PDF was downloaded.
    """
    url = normalize_url(url)

    methods = []
    if _requests is not None:
        methods.append(("requests", _download_requests))
    methods.append(("urllib", _download_urllib))
    if _sync_playwright is not None:
        methods.append(("playwright", _download_playwright))

    for name, fn in methods:
        try:
            if fn(url, output_path):
                # Verify it's actually a PDF
                with open(output_path, "rb") as f:
                    header = f.read(8)
                if header.startswith(b"%PDF"):
                    size = os.path.getsize(output_path)
                    print(f"Downloaded {size:,} bytes via {name}: {output_path}")
                    return True
                else:
                    # Not a PDF (probably HTML error page or JS redirect)
                    os.remove(output_path)
        except Exception:
            if os.path.exists(output_path):
                os.remove(output_path)
            continue

    return False


def _download_requests(url: str, output_path: str) -> bool:
    """Download using the requests library (handles HTTP/2, all manufacturers)."""
    resp = _requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=20,
        allow_redirects=True,
    )
    resp.raise_for_status()
    if len(resp.content) == 0:
        return False
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return True


def _download_urllib(url: str, output_path: str) -> bool:
    """Download using Python urllib (fallback, HTTP/1.1 only)."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        with open(output_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def _download_playwright(url: str, output_path: str) -> bool:
    """Download using Playwright headless browser.

    Last-resort fallback for sites that require JavaScript execution
    (Broadcom doc viewer, Espressif, etc.). Handles two patterns:
    1. Page triggers a file download (intercepted via expect_download)
    2. Page navigates directly to a PDF (read from response body)
    """
    with _sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # First try: expect a download event (some sites trigger JS downloads)
            try:
                with page.expect_download(timeout=15000) as dl_info:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                download = dl_info.value
                download.save_as(output_path)
                return os.path.exists(output_path) and os.path.getsize(output_path) > 0
            except Exception:
                pass

            # Second try: navigate and read the response body directly
            resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            if resp is None:
                return False
            body = resp.body()
            if body and body[:4] == b"%PDF":
                with open(output_path, "wb") as f:
                    f.write(body)
                return True
            return False
        finally:
            page.close()
            browser.close()


def try_alternative_sources(mpn: str, output_path: str) -> bool:
    """Try downloading from known mirror/alternative datasheet sources.

    When the primary manufacturer URL fails (Microchip 403, ST timeout),
    try alternative sources that host the same datasheets.
    """
    alternatives = []
    mpn_upper = mpn.upper()

    # Microchip: try direct product document URL
    if any(x in mpn_upper for x in ("ATMEGA", "ATTINY", "PIC", "SAMD", "SAM")):
        alternatives.append(
            f"https://ww1.microchip.com/downloads/aemDocuments/documents/MCU08/ProductDocuments/DataSheets/{mpn}-DataSheet.pdf"
        )

    for alt_url in alternatives:
        if download_pdf(alt_url, output_path):
            return True

    return False


def _extract_pdf_text(pdf_path: str, max_pages: int = 3) -> str:
    """Extract text from the first few pages of a PDF.

    Tries pdftotext (poppler-utils) first for best quality, then falls
    back to scanning raw PDF bytes for ASCII strings.
    """
    # Strategy 1: pdftotext (best quality, handles all encodings)
    try:
        result = subprocess.run(
            ["pdftotext", "-l", str(max_pages), pdf_path, "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Strategy 2: raw byte scanning (no dependencies needed)
    try:
        with open(pdf_path, "rb") as f:
            raw = f.read(200_000)  # first ~200KB covers first few pages
        # Extract readable ASCII sequences (4+ chars)
        strings = re.findall(rb"[\x20-\x7e]{4,}", raw)
        return " ".join(s.decode("ascii", errors="ignore") for s in strings)
    except Exception:
        return ""


def verify_datasheet(
    pdf_path: str,
    mpn: str,
    description: str = "",
    manufacturer: str = "",
) -> dict:
    """Verify a downloaded PDF is actually the correct datasheet.

    Extracts text from the first few pages and checks for the MPN,
    manufacturer, and description keywords. Returns a dict with:
      - verified: bool (True if MPN found in text)
      - confidence: "verified" | "likely" | "unverified" | "wrong"
      - mpn_found: bool
      - manufacturer_found: bool
      - keyword_hits: int (how many description keywords matched)
      - keyword_total: int
      - details: str (human-readable explanation)
    """
    text = _extract_pdf_text(pdf_path)
    if not text or len(text) < 50:
        return {
            "verified": False,
            "confidence": "unverified",
            "mpn_found": False,
            "manufacturer_found": False,
            "keyword_hits": 0,
            "keyword_total": 0,
            "details": "Could not extract text from PDF",
        }

    text_upper = text.upper()

    # Check for MPN — try exact, then base MPN without common suffixes
    mpn_upper = mpn.upper()
    mpn_found = mpn_upper in text_upper

    if not mpn_found:
        # Strip common ordering suffixes and try again
        # e.g., TPS61023DRLR -> TPS61023, BSS138LT1G -> BSS138
        base_mpn = re.sub(
            r"(DRLR|DRL|DGKR|DGK|DCKR|DCK|DBVR|DBV|PWPR|PWP|RGER|RGE|"
            r"RGTR|RGT|NRND|TR|CT|ND|LT1G|LT3G|BK|PBF|-ND)$",
            "", mpn_upper,
        )
        if base_mpn and len(base_mpn) >= 4 and base_mpn != mpn_upper:
            mpn_found = base_mpn in text_upper

    # Check manufacturer name
    mfg_found = False
    if manufacturer:
        mfg_upper = manufacturer.upper()
        # Try full name and common short forms
        mfg_found = mfg_upper in text_upper
        if not mfg_found:
            # Try first word (e.g., "Texas" from "Texas Instruments")
            first_word = mfg_upper.split()[0] if " " in mfg_upper else ""
            if first_word and len(first_word) >= 4:
                mfg_found = first_word in text_upper

    # Check description keywords
    keywords = []
    if description:
        # Extract meaningful words from description (skip noise)
        skip = {"the", "a", "an", "for", "and", "or", "with", "in", "to",
                "of", "at", "by", "on", "no", "w", "smd", "smt"}
        for word in re.split(r"[\s/,_-]+", description):
            w = word.strip().upper()
            if len(w) >= 3 and w not in skip and not re.match(r"^\d+$", w):
                keywords.append(w)

    keyword_hits = sum(1 for kw in keywords if kw in text_upper) if keywords else 0
    keyword_total = len(keywords)

    # Determine confidence level
    if mpn_found:
        confidence = "verified"
        details = f"MPN '{mpn}' found in PDF text"
    elif mfg_found and keyword_hits >= max(1, keyword_total // 2):
        confidence = "likely"
        details = (f"MPN not found but manufacturer '{manufacturer}' present "
                   f"with {keyword_hits}/{keyword_total} description keywords")
    elif keyword_hits >= max(2, keyword_total * 2 // 3):
        confidence = "likely"
        details = f"{keyword_hits}/{keyword_total} description keywords found"
    elif keyword_hits == 0 and keyword_total >= 3 and not mfg_found:
        confidence = "wrong"
        details = (f"No MPN, manufacturer, or description keywords found in PDF "
                   f"(0/{keyword_total} keywords)")
    else:
        confidence = "unverified"
        details = (f"MPN not found; {keyword_hits}/{keyword_total} keywords, "
                   f"manufacturer {'found' if mfg_found else 'not found'}")

    return {
        "verified": mpn_found,
        "confidence": confidence,
        "mpn_found": mpn_found,
        "manufacturer_found": mfg_found,
        "keyword_hits": keyword_hits,
        "keyword_total": keyword_total,
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser(description="Download a datasheet PDF")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="Direct URL to the PDF")
    group.add_argument("--search", metavar="MPN", help="Search DigiKey by MPN and download the datasheet")
    parser.add_argument("--output", "-o", help="Output file path (default: <MPN>.pdf in current directory)")
    parser.add_argument("--json", action="store_true", help="Output result as JSON (for script integration)")
    args = parser.parse_args()

    if args.search:
        product = search_digikey(args.search)
        if not product:
            if args.json:
                json.dump({"success": False, "error": "Part not found"}, sys.stdout)
            sys.exit(2)

        mpn = product.get("ManufacturerProductNumber", args.search)
        desc = product.get("Description", {}).get("ProductDescription", "")
        ds_url = product.get("DatasheetUrl", "")
        output_path = args.output or (_friendly_filename(mpn, desc) + ".pdf")

        if args.json:
            result = {
                "mpn": mpn,
                "manufacturer": product.get("Manufacturer", {}).get("Name", ""),
                "description": product.get("Description", {}).get("ProductDescription", ""),
                "datasheet_url": ds_url,
            }

        if not ds_url:
            print(f"No datasheet URL for {mpn}", file=sys.stderr)
            if args.json:
                result["success"] = False
                result["error"] = "No datasheet URL in DigiKey listing"
                json.dump(result, sys.stdout)
            sys.exit(2)

        if download_pdf(ds_url, output_path):
            vr = verify_datasheet(output_path, mpn, desc,
                                  product.get("Manufacturer", {}).get("Name", ""))
            if vr["confidence"] == "wrong":
                print(f"WARNING: Downloaded PDF may be wrong datasheet for {mpn}",
                      file=sys.stderr)
                print(f"  {vr['details']}", file=sys.stderr)
            elif vr["confidence"] == "unverified":
                print(f"  Verification inconclusive for {mpn}: {vr['details']}",
                      file=sys.stderr)
            if args.json:
                result["success"] = True
                result["output"] = output_path
                result["verification"] = vr
                json.dump(result, sys.stdout)
            sys.exit(0)

        # Try alternative sources
        print(f"Primary URL failed, trying alternatives for {mpn}...", file=sys.stderr)
        if try_alternative_sources(mpn, output_path):
            vr = verify_datasheet(output_path, mpn, desc,
                                  product.get("Manufacturer", {}).get("Name", ""))
            if vr["confidence"] == "wrong":
                print(f"WARNING: Downloaded PDF may be wrong datasheet for {mpn}",
                      file=sys.stderr)
                print(f"  {vr['details']}", file=sys.stderr)
            if args.json:
                result["success"] = True
                result["output"] = output_path
                result["source"] = "alternative"
                result["verification"] = vr
                json.dump(result, sys.stdout)
            sys.exit(0)

        print(f"Failed to download datasheet for {mpn}", file=sys.stderr)
        if args.json:
            result["success"] = False
            result["error"] = "All download methods failed"
            json.dump(result, sys.stdout)
        sys.exit(1)

    else:
        # Direct URL mode
        url = args.url
        output_path = args.output or "datasheet.pdf"

        if download_pdf(url, output_path):
            if args.json:
                json.dump({"success": True, "output": output_path, "url": url}, sys.stdout)
            sys.exit(0)
        else:
            print(f"Failed to download PDF from {url}", file=sys.stderr)
            if args.json:
                json.dump({"success": False, "url": url, "error": "Download failed"}, sys.stdout)
            sys.exit(1)


if __name__ == "__main__":
    main()
