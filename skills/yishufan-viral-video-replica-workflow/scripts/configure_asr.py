#!/usr/bin/env python3
"""Configure Aliyun ASR for watch without exposing the key in command history."""

from __future__ import annotations

import argparse
import getpass
import os
import tempfile
from pathlib import Path


DEFAULT_CONFIG = Path.home() / ".config" / "watch" / ".env"


def read_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def update_lines(existing: str, updates: dict[str, str]) -> str:
    remaining = dict(updates)
    output: list[str] = []
    for raw in existing.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(raw)
    if output and output[-1] != "":
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(output).rstrip() + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".watch-env-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Aliyun Paraformer for the watch backend.")
    parser.add_argument("--endpoint", required=False)
    parser.add_argument("--models", default="paraformer-v2,paraformer-v1")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--from-env", action="store_true", help="Read DASHSCOPE_API_KEY from the current process")
    parser.add_argument("--check", action="store_true", help="Report configuration presence without showing secrets")
    args = parser.parse_args()
    path = args.config.expanduser().resolve()
    values = read_values(path)
    if args.check:
        keys = ("DASHSCOPE_API_KEY", "DASHSCOPE_ENDPOINT", "DASHSCOPE_ASR_MODELS")
        values = {key: os.environ.get(key) or values.get(key) for key in keys}
        print(f"config={path}")
        for key in keys:
            print(f"{key}: configured={bool(values.get(key))}")
        return 0 if all(values.get(key) for key in ("DASHSCOPE_API_KEY", "DASHSCOPE_ENDPOINT")) else 2

    endpoint = args.endpoint or values.get("DASHSCOPE_ENDPOINT")
    if not endpoint:
        parser.error("--endpoint is required the first time")
    key = os.environ.get("DASHSCOPE_API_KEY") if args.from_env else ""
    if not key:
        key = getpass.getpass("DASHSCOPE_API_KEY (input hidden): ").strip()
    if not key:
        parser.error("DASHSCOPE_API_KEY cannot be empty")
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    content = update_lines(
        existing,
        {
            "DASHSCOPE_API_KEY": key,
            "DASHSCOPE_ENDPOINT": endpoint.rstrip("/"),
            "DASHSCOPE_ASR_MODELS": args.models,
            "SETUP_COMPLETE": "true",
        },
    )
    atomic_write(path, content)
    print(f"configured={path}")
    print(f"endpoint={endpoint.rstrip('/')}")
    print(f"models={args.models}")
    print("api_key=configured (value hidden)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
