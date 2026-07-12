#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")


def request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {body}") from exc


def main() -> int:
    check = request("GET", "/api/v1/legal/wecom-poc/archive-check/current")["data"]
    if not check["ready"]:
        raise RuntimeError(f"archive-check/current not ready: {json.dumps(check, ensure_ascii=False)}")

    pull = request("POST", "/api/v1/legal/wecom-archive/pull")["data"]
    if pull["processed"] < 1:
        raise RuntimeError(f"sidecar mock pull did not process messages: {json.dumps(pull, ensure_ascii=False)}")

    query = urllib.parse.urlencode({"group_id": "group_001", "page_size": 20})
    media = request("GET", f"/api/v1/legal/media-files?{query}")["data"]
    if media["total"] < 1:
        raise RuntimeError("sidecar mock pull did not create media files")

    print(
        json.dumps(
            {
                "ok": True,
                "base_url": BASE_URL,
                "pull": pull,
                "media_total": media["total"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"acceptance wecom sidecar mock failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
