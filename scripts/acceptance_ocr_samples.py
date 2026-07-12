#!/usr/bin/env python3
import json
import os
import sys
import time
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {body}") from exc


def file_message(seq: int, msgid: str, filename: str) -> dict:
    return {
        "seq": seq,
        "msgid": msgid,
        "roomid": "group_001",
        "from": "user_acceptance",
        "msgtype": "file",
        "file": {"filename": filename, "md5sum": "acceptance", "filesize": 100},
        "msgtime": 1780300000000,
    }


def main() -> int:
    suffix = str(int(time.time()))
    samples = [
        ("judgment", "判决书.pdf", "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三\n判决如下。", "judgment"),
        ("mediation", "调解书.pdf", "民事调解书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三\n双方达成调解。", "judgment"),
        ("ruling", "裁定书.pdf", "民事裁定书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三\n裁定如下。", "judgment"),
        ("court", "开庭传票.pdf", "传票\n案号：(2026)黔0281民初3118号\n被告：张三\n定于2026年7月2日 下午3点开庭。", "court_notice"),
        ("payment", "缴费通知.pdf", "案件(2026)黔0281民初3118号缴费通知：诉讼费400元，7天内完成。", "payment_notice"),
    ]
    messages = []
    ocr_text_by_msgid = {}
    expected = {}
    for index, (name, filename, text, event_type) in enumerate(samples, start=1):
        msgid = f"msg_acceptance_{name}_{suffix}"
        messages.append(file_message(9000 + index, msgid, filename))
        ocr_text_by_msgid[msgid] = text
        expected[msgid] = event_type

    replay = request(
        "POST",
        "/api/v1/legal/wecom-archive/replay-with-ocr",
        {"messages": messages, "ocr_text_by_msgid": ocr_text_by_msgid},
    )["data"]

    if replay["ocr_failed"] != 0 or replay["ocr_processed"] != len(samples):
        raise RuntimeError(f"OCR replay failed: {json.dumps(replay, ensure_ascii=False)}")

    result_by_msgid = {item["msgid"]: item for item in replay["ocr_results"]}
    for msgid, event_type in expected.items():
        item = result_by_msgid[msgid]
        if item["event_type"] != event_type:
            raise RuntimeError(f"{msgid} event_type expected {event_type}, got {item['event_type']}")
        if item.get("requires_review"):
            raise RuntimeError(f"{msgid} unexpectedly requires review: {json.dumps(item, ensure_ascii=False)}")

    query = urllib.parse.urlencode({"page_size": 50, "sync_target": "kdocs"})
    logs = request("GET", f"/api/v1/legal/document-sync-logs?{query}")["data"]["items"]
    sync_types = {item["sync_type"] for item in logs}
    required_sync_types = {"legal_document_upload", "enforcement_progress", "court_time", "payment_registration"}
    missing = sorted(required_sync_types - sync_types)
    if missing:
        raise RuntimeError(f"missing sync logs: {missing}")

    print(
        json.dumps(
            {
                "ok": True,
                "base_url": BASE_URL,
                "ocr_processed": replay["ocr_processed"],
                "sync_types_checked": sorted(required_sync_types),
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
        print(f"acceptance ocr samples failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
