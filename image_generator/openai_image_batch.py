"""
OpenAI Batch API adapter for image generation.

Endpoint: /v1/images/generations (支援 batch，50% 折扣)
結果以 JSONL 格式下載，靠 custom_id 對應各 scene。
"""

import base64
import io
import json
from openai import OpenAI

client = OpenAI()

_ASPECT_TO_SIZE = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1":  "1024x1024",
}

_PENDING_STATUSES   = {"validating", "in_progress", "finalizing"}
_FAILED_STATUSES    = {"failed", "cancelled"}


def submit_image_batch(scenes_map: dict, model_name: str, quality: str) -> str:
    """
    scenes_map: {custom_id: {"prompt": str, "aspect_ratio": str}}
    Returns OpenAI batch id (e.g. "batch_abc123").
    """
    lines = []
    for custom_id, info in scenes_map.items():
        size = _ASPECT_TO_SIZE.get(info["aspect_ratio"], "1024x1024")
        lines.append(json.dumps({
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/images/generations",
            "body": {
                "model": model_name,
                "prompt": info["prompt"],
                "size": size,
                "quality": quality,
                "response_format": "b64_json",
                "n": 1,
            },
        }))
    jsonl_bytes = "\n".join(lines).encode("utf-8")
    uploaded = client.files.create(
        file=("batch_images.jsonl", io.BytesIO(jsonl_bytes)),
        purpose="batch",
    )
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/images/generations",
        completion_window="24h",
    )
    return batch.id


def get_image_batch_status(batch_id: str) -> str:
    """輕量查詢，只回傳狀態字串，不下載結果。供 batch_status.py 使用。"""
    status = client.batches.retrieve(batch_id).status
    if status in _PENDING_STATUSES:
        return "IN_PROGRESS"
    if status == "expired":
        return "EXPIRED"
    if status in _FAILED_STATUSES:
        return "FAILED"
    if status == "completed":
        return "COMPLETED"
    return status.upper()


def collect_image_batch(batch_id: str) -> tuple[str, dict, dict]:
    """
    Returns (status, successes, failures).
      status:   "pending" | "completed" | "partial" | "failed" | "expired"
      successes: {custom_id: image_bytes}
      failures:  {custom_id: error_str}
    """
    batch = client.batches.retrieve(batch_id)

    if batch.status in _PENDING_STATUSES:
        return "pending", {}, {}
    if batch.status == "expired":
        return "expired", {}, {}
    if batch.status in _FAILED_STATUSES:
        return "failed", {}, {}

    # completed — download output file
    successes: dict = {}
    failures: dict = {}

    if batch.output_file_id:
        content = client.files.content(batch.output_file_id).text
        for line in content.strip().split("\n"):
            if not line:
                continue
            result = json.loads(line)
            cid = result["custom_id"]
            err = result.get("error")
            if err:
                failures[cid] = err.get("message", "unknown error")
                continue
            resp = result.get("response", {})
            if resp.get("status_code") != 200:
                failures[cid] = f"HTTP {resp.get('status_code')}"
                continue
            try:
                b64 = resp["body"]["data"][0]["b64_json"]
                successes[cid] = base64.b64decode(b64)
            except Exception as e:
                failures[cid] = str(e)

    if batch.error_file_id:
        error_content = client.files.content(batch.error_file_id).text
        for line in error_content.strip().split("\n"):
            if not line:
                continue
            result = json.loads(line)
            cid = result.get("custom_id", "unknown")
            if cid not in failures and cid not in successes:
                failures[cid] = result.get("error", {}).get("message", "batch error")

    status = "partial" if failures else "completed"
    return status, successes, failures
