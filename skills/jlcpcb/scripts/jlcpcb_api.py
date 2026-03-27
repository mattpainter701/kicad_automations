"""JLCPCB Partner API client.

Authentication: JOP-HMAC-SHA256 signing with AppID/Accesskey/SecretKey.
Credentials loaded from ~/.config/secrets.env:
  - JLCPCB_AppID (optional — defaults to Accesskey if not set)
  - JLCPCB_Accesskey
  - JLCPCB_SecretKey

Usage:
    from jlcpcb_api import JLCPCBClient
    client = JLCPCBClient()
    result = client.pcb_quote(layers=2, width=100, height=80, qty=5)
"""

import hashlib
import hmac
import json
import os
import secrets as secrets_mod
import sys
import time
import urllib.parse
import urllib.request

# The Partner API lives on the main jlcpcb.com domain
BASE_URL = "https://jlcpcb.com/api/overseas/openapi"


def load_secrets():
    """Load API credentials from ~/.config/secrets.env."""
    path = os.path.expanduser("~/.config/secrets.env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


class JLCPCBClient:
    """JLCPCB Partner API client with JOP-HMAC-SHA256 authentication."""

    def __init__(self, app_id=None, access_key=None, secret_key=None, base_url=None):
        load_secrets()
        self.access_key = access_key or os.environ.get("JLCPCB_Accesskey", "")
        self.secret_key = secret_key or os.environ.get("JLCPCB_SecretKey", "")
        # AppID may be separate or same as access key
        self.app_id = app_id or os.environ.get("JLCPCB_AppID", self.access_key)
        self.base_url = base_url or BASE_URL
        if not self.access_key or not self.secret_key:
            raise ValueError(
                "JLCPCB_Accesskey and JLCPCB_SecretKey must be set in "
                "~/.config/secrets.env or passed as arguments"
            )

    def _sign(self, method, uri, timestamp, nonce, body_str=""):
        """Generate JOP-HMAC-SHA256 signature.

        String-to-sign: METHOD\\nURI\\nTIMESTAMP\\nNONCE\\nBODY\\n
        """
        string_to_sign = f"{method.upper()}\n{uri}\n{timestamp}\n{nonce}\n{body_str}\n"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _auth_header(self, method, uri, timestamp, nonce, body_str=""):
        """Build the Authorization header value."""
        signature = self._sign(method, uri, timestamp, nonce, body_str)
        return (
            f"JOP-HMAC-SHA256 "
            f'appid="{self.app_id}",'
            f'accesskey="{self.access_key}",'
            f'timestamp="{timestamp}",'
            f'nonce="{nonce}",'
            f'signature="{signature}"'
        )

    def _request(self, method, path, body=None):
        """Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST)
            path: API path (e.g. /pcb/calculate)
            body: Request body dict (for POST)

        Returns:
            (response_dict, http_status_code)
        """
        timestamp = str(int(time.time()))
        nonce = secrets_mod.token_hex(16)  # 32-char hex
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        uri = path  # URI for signing is the path portion

        url = f"{self.base_url}{path}"

        auth = self._auth_header(method.upper(), uri, timestamp, nonce, body_str)

        headers = {
            "Content-Type": "application/json",
            "Authorization": auth,
            "Accept": "application/json",
            "User-Agent": "jlcpcb-skill/1.0",
        }

        data = body_str.encode("utf-8") if body_str else None
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                error_json = json.loads(error_body)
            except json.JSONDecodeError:
                error_json = {"raw": error_body[:500]}
            return {"error": True, "status": e.code, "detail": error_json}, e.code
        except urllib.error.URLError as e:
            return {"error": True, "detail": str(e)}, 0

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, body=None):
        return self._request("POST", path, body)

    # --- PCB API ---

    def pcb_quote(
        self,
        layers=2,
        width=100.0,
        height=80.0,
        qty=5,
        thickness=1.6,
        color=1,
        surface_finish=1,
        copper_weight=1.0,
        country="US",
        post_code="94102",
        city="San Francisco",
    ):
        """Get PCB fabrication price quote (no gerber needed).

        Args:
            layers: Number of copper layers (1, 2, 4, 6)
            width: Board width in mm
            height: Board height in mm
            qty: Number of boards
            thickness: Board thickness in mm
            color: Solder mask color (1=green, etc.)
            surface_finish: 1=HASL, 2=LeadFreeHASL, 3=ENIG
            copper_weight: Outer copper weight in oz
            country: Shipping country code
            post_code: Shipping postal code
            city: Shipping city

        Returns:
            (response_dict, status_code)
        """
        return self.post(
            "/pcb/calculate",
            {
                "orderType": 1,
                "pcbParam": {
                    "layer": layers,
                    "width": width,
                    "length": height,
                    "qty": qty,
                    "thickness": thickness,
                    "pcbColor": color,
                    "surfaceFinish": surface_finish,
                    "copperWeight": copper_weight,
                    "goldFinger": 0,
                    "materialDetails": 1,
                    "panelFlag": 0,
                    "differentDesign": 1,
                },
                "country": country,
                "postCode": post_code,
                "city": city,
            },
        )

    def pcb_upload_gerber(self, gerber_zip_path):
        """Upload gerber ZIP file.

        Returns fileKey and batchNum for order creation.
        For multipart uploads, sign with empty body string.
        """

        timestamp = str(int(time.time()))
        nonce = secrets_mod.token_hex(16)
        uri = "/pcb/uploadGerber"
        url = f"{self.base_url}{uri}"

        # For multipart, sign with empty body
        auth = self._auth_header("POST", uri, timestamp, nonce, "")

        # Build multipart form data
        boundary = f"----JLCPCBBoundary{secrets_mod.token_hex(8)}"
        filename = os.path.basename(gerber_zip_path)

        with open(gerber_zip_path, "rb") as f:
            file_data = f.read()

        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: application/zip\r\n\r\n"
            ).encode("utf-8")
            + file_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": auth,
            "Accept": "application/json",
            "User-Agent": "jlcpcb-skill/1.0",
        }

        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                error_json = json.loads(error_body)
            except json.JSONDecodeError:
                error_json = {"raw": error_body[:500]}
            return {"error": True, "status": e.code, "detail": error_json}, e.code

    def pcb_create_order(self, file_key, batch_num, pcb_params):
        """Create a PCB order after gerber upload."""
        body = {
            "fileKey": file_key,
            "batchNum": batch_num,
            **pcb_params,
        }
        return self.post("/pcb/create", body)

    def pcb_order_status(self, order_number):
        """Get order production/WIP status."""
        return self.post("/pcb/wip/get", {"orderNumber": order_number})


def probe_api(client):
    """Test API connectivity with a price quote request."""
    print(f"Base URL: {client.base_url}")
    print(f"App ID:   {client.app_id[:8]}...")
    print(f"Access:   {client.access_key[:8]}...")
    print()

    # Test 1: PCB quote (simplest endpoint, no file upload needed)
    print("=" * 50)
    print("TEST: PCB Price Quote (2-layer, 100x80mm, qty 5)")
    print("=" * 50)
    result, status = client.pcb_quote(
        layers=2,
        width=100,
        height=80,
        qty=5,
        thickness=1.6,
        color=1,
        surface_finish=1,
    )
    print(f"Status: {status}")
    if status == 200 and not result.get("error"):
        print(f"Response: {json.dumps(result, indent=2)[:500]}")
    else:
        print(f"Error: {json.dumps(result, indent=2)[:500]}")

    # If auth failed, try alternate signing: full URL path instead of relative
    if status in (401, 403):
        print()
        print("Retrying with full URL path in signature...")
        full_path = "/api/overseas/openapi/pcb/calculate"
        body = json.dumps(
            {
                "orderType": 1,
                "pcbParam": {
                    "layer": 2,
                    "width": 100.0,
                    "length": 80.0,
                    "qty": 5,
                    "thickness": 1.6,
                    "pcbColor": 1,
                    "surfaceFinish": 1,
                    "copperWeight": 1.0,
                    "goldFinger": 0,
                    "materialDetails": 1,
                    "panelFlag": 0,
                    "differentDesign": 1,
                },
                "country": "US",
                "postCode": "94102",
                "city": "San Francisco",
            },
            separators=(",", ":"),
        )

        timestamp = str(int(time.time()))
        nonce = secrets_mod.token_hex(16)
        sig = client._sign("POST", full_path, timestamp, nonce, body)
        auth = (
            f"JOP-HMAC-SHA256 "
            f'appid="{client.app_id}",'
            f'accesskey="{client.access_key}",'
            f'timestamp="{timestamp}",'
            f'nonce="{nonce}",'
            f'signature="{sig}"'
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": auth,
            "Accept": "application/json",
        }
        url = f"https://jlcpcb.com{full_path}"
        req = urllib.request.Request(url, data=body.encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                print(f"[{resp.status}] {json.dumps(data, indent=2)[:500]}")
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")[:300]
            print(f"[{e.code}] {err}")


if __name__ == "__main__":
    client = JLCPCBClient()

    if "--probe" in sys.argv:
        probe_api(client)
    elif "--quote" in sys.argv:
        # Quick quote test
        result, status = client.pcb_quote()
        print(f"Status: {status}")
        print(json.dumps(result, indent=2))
    else:
        print("Usage: py jlcpcb_api.py --probe | --quote")
        print()
        print("Environment variables (set in ~/.config/secrets.env):")
        print("  JLCPCB_AppID      - Application ID (optional, defaults to Accesskey)")
        print("  JLCPCB_Accesskey  - API access key")
        print("  JLCPCB_SecretKey  - API secret key")
