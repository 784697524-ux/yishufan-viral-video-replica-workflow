#!/usr/bin/env python3
"""Aliyun DashScope/Bailian non-realtime ASR fallback for /watch."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests


UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com"
DEFAULT_MODELS = ["paraformer-v2", "paraformer-v1"]
FINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}


class TryNextModel(RuntimeError):
    pass


def _api_base(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/compatible-mode/v1"):
        return endpoint[: -len("/compatible-mode/v1")] + "/api/v1"
    if endpoint.endswith("/api/v1"):
        return endpoint
    return endpoint + "/api/v1"


def _checked_json(response: requests.Response, action: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise SystemExit(f"{action} returned non-JSON: HTTP {response.status_code} {response.text[:300]}") from exc

    if response.status_code in {401, 403}:
        code = payload.get("code") or payload.get("error", {}).get("code") or ""
        message = payload.get("message") or payload.get("error", {}).get("message") or ""
        raise TryNextModel(f"{action}: HTTP {response.status_code} {code} {message}")
    if response.status_code >= 400:
        raise SystemExit(f"{action} failed: HTTP {response.status_code} {json.dumps(payload, ensure_ascii=False)[:800]}")
    return payload


def _upload(api_key: str, model: str, media_path: Path) -> str:
    policy_response = requests.get(
        UPLOAD_POLICY_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        params={"action": "getPolicy", "model": model},
        timeout=30,
    )
    policy = _checked_json(policy_response, f"aliyun {model} get upload policy").get("data") or {}
    if not policy:
        raise SystemExit(f"aliyun {model} upload policy missing data")

    safe_name = f"{uuid.uuid4().hex}{media_path.suffix.lower() or '.bin'}"
    key = f"{policy['upload_dir']}/{safe_name}"
    with media_path.open("rb") as file_obj:
        files = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (safe_name, file_obj),
        }
        upload_response = requests.post(policy["upload_host"], files=files, timeout=180)

    if upload_response.status_code in {401, 403}:
        raise TryNextModel(f"aliyun {model} upload: HTTP {upload_response.status_code}")
    if upload_response.status_code != 200:
        raise SystemExit(f"aliyun {model} upload failed: HTTP {upload_response.status_code} {upload_response.text[:500]}")
    return f"oss://{key}"


def _submit(api_key: str, api_base: str, model: str, file_url: str) -> str:
    parameters: dict[str, Any] = {
        "channel_id": [0],
        "timestamp_alignment_enabled": True,
        "disfluency_removal_enabled": False,
    }
    if model == "paraformer-v2":
        parameters["language_hints"] = ["zh", "en"]

    response = requests.post(
        f"{api_base}/services/audio/asr/transcription",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        },
        data=json.dumps({"model": model, "input": {"file_urls": [file_url]}, "parameters": parameters}),
        timeout=60,
    )
    payload = _checked_json(response, f"aliyun {model} submit")
    task_id = payload.get("output", {}).get("task_id")
    if not task_id:
        raise SystemExit(f"aliyun {model} submit missing task_id: {json.dumps(payload, ensure_ascii=False)[:500]}")
    return str(task_id)


def _fetch_task(api_key: str, api_base: str, task_id: str) -> dict[str, Any]:
    url = f"{api_base}/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code in {404, 405}:
        response = requests.post(url, headers=headers, timeout=30)
    return _checked_json(response, "aliyun task poll")


def _wait_task(api_key: str, api_base: str, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + int(os.environ.get("DASHSCOPE_ASR_TIMEOUT", "900"))
    interval = float(os.environ.get("DASHSCOPE_ASR_POLL_INTERVAL", "5"))
    while True:
        payload = _fetch_task(api_key, api_base, task_id)
        status = payload.get("output", {}).get("task_status")
        if status in FINAL_STATUSES:
            return payload
        if time.monotonic() >= deadline:
            raise SystemExit(f"aliyun task timeout: task_id={task_id}, last_status={status}")
        time.sleep(interval)


def _segments_from_result(result: dict[str, Any]) -> list[dict]:
    segments: list[dict] = []
    for transcript in result.get("transcripts", []) or []:
        for sentence in transcript.get("sentences", []) or []:
            text = (sentence.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start": round(float(sentence.get("begin_time") or 0) / 1000.0, 2),
                    "end": round(float(sentence.get("end_time") or 0) / 1000.0, 2),
                    "text": text,
                }
            )
    return segments


def _download_segments(task_payload: dict[str, Any]) -> list[dict]:
    results = task_payload.get("output", {}).get("results") or []
    if not results:
        raise SystemExit(f"aliyun task missing results: {json.dumps(task_payload, ensure_ascii=False)[:500]}")
    first = results[0]
    if first.get("subtask_status") != "SUCCEEDED":
        raise SystemExit(f"aliyun subtask failed: {json.dumps(first, ensure_ascii=False)[:800]}")
    url = first.get("transcription_url")
    if not url:
        raise SystemExit(f"aliyun subtask missing transcription_url: {json.dumps(first, ensure_ascii=False)[:500]}")
    response = requests.get(url, timeout=120)
    if response.status_code >= 400:
        raise SystemExit(f"aliyun result download failed: HTTP {response.status_code}")
    return _segments_from_result(response.json())


def transcribe_file(media_path: Path, api_key: str) -> tuple[list[dict], str]:
    endpoint = os.environ.get("DASHSCOPE_ENDPOINT", DEFAULT_ENDPOINT)
    api_base = _api_base(endpoint)
    models = [
        item.strip()
        for item in os.environ.get("DASHSCOPE_ASR_MODELS", ",".join(DEFAULT_MODELS)).split(",")
        if item.strip()
    ]
    errors: list[str] = []
    for model in models:
        try:
            print(f"[watch] aliyun ASR upload via {model}…", file=sys.stderr)
            file_url = _upload(api_key, model, media_path)
            print(f"[watch] aliyun ASR submit via {model}…", file=sys.stderr)
            task_id = _submit(api_key, api_base, model, file_url)
            task_payload = _wait_task(api_key, api_base, task_id)
            if task_payload.get("output", {}).get("task_status") != "SUCCEEDED":
                raise SystemExit(f"aliyun {model} task failed: {json.dumps(task_payload, ensure_ascii=False)[:800]}")
            segments = _download_segments(task_payload)
            if not segments:
                raise SystemExit(f"aliyun {model} returned no transcript segments")
            return segments, f"aliyun-{model}"
        except TryNextModel as exc:
            errors.append(f"{model}: {exc}")
            print(f"[watch] aliyun ASR {model} unavailable — trying next model ({exc})", file=sys.stderr)
    raise SystemExit("Aliyun ASR failed on every model: " + " | ".join(errors))
