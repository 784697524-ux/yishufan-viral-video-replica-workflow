#!/usr/bin/env python3
"""Prepare deterministic reference-video evidence for the replica workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


SKILL_DIR = Path(__file__).resolve().parents[1]


def resolve_watch_dir() -> Path:
    """Prefer the bundled watch backend, with installed copies as fallbacks."""
    configured = os.environ.get("WATCH_SKILL_DIR")
    candidates = [
        Path(configured).expanduser() if configured else None,
        SKILL_DIR / "vendor" / "watch",
        Path.home() / ".agents" / "skills" / "watch",
        Path.home() / ".codex" / "skills" / "watch",
    ]
    for candidate in candidates:
        if candidate and (candidate / "scripts" / "watch.py").is_file():
            return candidate.resolve()
    return (SKILL_DIR / "vendor" / "watch").resolve()


WATCH_DIR = resolve_watch_dir()
WATCH_SCRIPT = WATCH_DIR / "scripts" / "watch.py"
WATCH_CONFIG = Path.home() / ".config" / "watch" / ".env"
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".wav"}
TIMELINE_INTERVAL_SECONDS = 0.5


def is_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def setting(name: str, dotenv: dict[str, str], default: str = "") -> str:
    return os.environ.get(name) or dotenv.get(name) or default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    data = json.loads(result.stdout)
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    audio = next((item for item in data.get("streams", []) if item.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    return {
        "duration_seconds": round(float(fmt.get("duration") or 0), 3),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "frame_rate": video.get("r_frame_rate"),
        "audio_codec": audio.get("codec_name"),
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
    }


def source_manifest(requested: str, media_path: Path | None = None) -> dict:
    manifest = {"requested_source": requested, "source_type": "url" if is_url(requested) else "local"}
    if media_path:
        resolved = media_path.expanduser().resolve()
        manifest.update(
            {
                "resolved_media": str(resolved),
                "filename": resolved.name,
                "sha256": sha256(resolved),
                **probe(resolved),
            }
        )
    return manifest


def parse_range(value: str) -> tuple[str, str]:
    if "-" not in value:
        raise argparse.ArgumentTypeError("反转区间必须写成 START-END，例如 8-13 或 00:23-00:30")
    start, end = (part.strip() for part in value.split("-", 1))
    if not start or not end:
        raise argparse.ArgumentTypeError("反转区间的起止时间不能为空")
    return start, end


def run_watch(source: str, out_dir: Path, resolution: int, start: str | None = None, end: str | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(WATCH_SCRIPT),
        source,
        "--detail",
        "balanced",
        "--resolution",
        str(resolution),
        "--out-dir",
        str(out_dir),
        "--no-whisper",
    ]
    if start is not None:
        command.extend(["--start", start])
    if end is not None:
        command.extend(["--end", end])
    if start is not None or end is not None:
        command.extend(["--fps", "2", "--no-dedup"])
    result = subprocess.run(command, text=True, capture_output=True)
    (out_dir / "watch_report.md").write_text(result.stdout, encoding="utf-8")
    (out_dir / "watch_stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"watch failed for {start or 'full'}-{end or 'full'}; see {out_dir / 'watch_stderr.log'}")
    frame_pattern = re.compile(r"^- `([^`]+)` \(t=([^,]+), reason=([^\)]+)\)$", re.MULTILINE)
    frames = [
        {"path": path, "timestamp": timestamp, "reason": reason}
        for path, timestamp, reason in frame_pattern.findall(result.stdout)
    ]
    return {"out_dir": str(out_dir), "frame_count": len(frames), "frames": frames}


def build_fixed_timeline_command(media_path: Path, frames_dir: Path, resolution: int) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(media_path),
        "-vf",
        f"fps=fps=2:start_time=0,scale={resolution}:-2",
        "-q:v",
        "3",
        str(frames_dir / "frame_%04d.jpg"),
    ]


def extract_fixed_timeline(media_path: Path, out_dir: Path, duration_seconds: float, resolution: int) -> dict:
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("frame_*.jpg"):
        stale.unlink()
    subprocess.run(build_fixed_timeline_command(media_path, frames_dir, resolution), check=True)
    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    frames = [
        {
            "path": str(path),
            "timestamp_seconds": round(index * TIMELINE_INTERVAL_SECONDS, 3),
        }
        for index, path in enumerate(frame_paths)
    ]
    manifest = {
        "source": str(media_path),
        "duration_seconds": duration_seconds,
        "interval_seconds": TIMELINE_INTERVAL_SECONDS,
        "frame_count": len(frames),
        "last_timestamp_seconds": frames[-1]["timestamp_seconds"] if frames else None,
        "frames": frames,
    }
    manifest_path = out_dir / "timeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "out_dir": str(out_dir),
        "frame_count": len(frames),
        "frames": frames,
        "manifest": str(manifest_path),
    }


def locate_downloaded_media(full_dir: Path) -> Path:
    candidates = [
        path
        for path in full_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES and path.name != "audio.mp3"
    ]
    if not candidates:
        raise RuntimeError("watch completed but no downloaded media file was found")
    return max(candidates, key=lambda item: item.stat().st_size)


def extract_audio(media_path: Path, audio_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(audio_path),
    ]
    subprocess.run(command, check=True)


def write_srt(path: Path, segments: list[dict]) -> None:
    def stamp(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, rem = divmod(millis, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        secs, ms = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    lines: list[str] = []
    for index, segment in enumerate(segments, 1):
        lines.extend(
            [
                str(index),
                f"{stamp(float(segment['start']))} --> {stamp(float(segment['end']))}",
                str(segment["text"]),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def transcribe_models(audio_path: Path, out_dir: Path, api_key: str, endpoint: str, models: list[str]) -> dict[str, list[dict]]:
    sys.path.insert(0, str(WATCH_DIR / "scripts"))
    from aliyun_asr import transcribe_file  # type: ignore

    old_endpoint = os.environ.get("DASHSCOPE_ENDPOINT")
    old_models = os.environ.get("DASHSCOPE_ASR_MODELS")
    os.environ["DASHSCOPE_ENDPOINT"] = endpoint
    outputs: dict[str, list[dict]] = {}
    try:
        for model in models:
            os.environ["DASHSCOPE_ASR_MODELS"] = model
            segments, used_model = transcribe_file(audio_path, api_key)
            model_dir = out_dir / model
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "segments.json").write_text(
                json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            write_srt(model_dir / "transcript.srt", segments)
            (model_dir / "transcript.txt").write_text(
                "\n".join(str(item["text"]) for item in segments) + "\n", encoding="utf-8"
            )
            outputs[used_model.removeprefix("aliyun-")] = segments
    finally:
        if old_endpoint is None:
            os.environ.pop("DASHSCOPE_ENDPOINT", None)
        else:
            os.environ["DASHSCOPE_ENDPOINT"] = old_endpoint
        if old_models is None:
            os.environ.pop("DASHSCOPE_ASR_MODELS", None)
        else:
            os.environ["DASHSCOPE_ASR_MODELS"] = old_models
    return outputs


def normalize_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()


def compare_segments(primary: list[dict], secondary: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for first in primary:
        best = None
        best_overlap = 0.0
        for second in secondary:
            overlap = max(0.0, min(float(first["end"]), float(second["end"])) - max(float(first["start"]), float(second["start"])))
            if overlap > best_overlap:
                best = second
                best_overlap = overlap
        secondary_text = str(best["text"]) if best else ""
        primary_text = str(first["text"])
        rows.append(
            {
                "start": first["start"],
                "end": first["end"],
                "primary": primary_text,
                "secondary": secondary_text,
                "status": "一致" if secondary_text and normalize_text(primary_text) == normalize_text(secondary_text) else "需复核",
            }
        )
    return rows


def md_escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_evidence_report(path: Path, manifest: dict, runs: dict, transcripts: dict[str, list[dict]], comparison: list[dict]) -> None:
    lines = [
        "# 参考视频证据清单",
        "",
        "> 本文件是机器生成的素材与ASR证据清单，不等于最终剧情分析。必须查看列出的全部关键帧后再写 `01_reference_analysis.md`。",
        "",
        "## 素材身份",
        "",
        f"- 请求源：`{md_escape(manifest['requested_source'])}`",
        f"- 实际媒体：`{md_escape(manifest.get('resolved_media', ''))}`",
        f"- SHA-256：`{md_escape(manifest.get('sha256', ''))}`",
        f"- 时长：{manifest.get('duration_seconds', '')} 秒",
        f"- 画幅：{manifest.get('width', '')}×{manifest.get('height', '')}",
        "",
        "## 抽帧结果",
        "",
    ]
    for name, run in runs.items():
        lines.append(f"- {name}：{run['frame_count']} 张，目录 `{run['out_dir']}/frames`")
    lines.extend(
        [
            "",
            "必须逐张查看“全片固定0.5秒时间线”，并在复刻合同中记录实际查看数量和最后时间戳；场景关键帧不能代替固定时间线。",
            "术语说明：这里只能称为关键帧/固定0.5秒时间线/重点区间密集抽帧分析，不得声称查看了每一个原始视频帧。",
            "",
        ]
    )
    for model, segments in transcripts.items():
        lines.extend([f"## ASR：{model}", "", "| 时间码 | 文本 |", "|---|---|"])
        for segment in segments:
            lines.append(f"| {float(segment['start']):.2f}-{float(segment['end']):.2f} | {md_escape(segment['text'])} |")
        lines.append("")
    lines.extend(["## 双模型对照", "", "| 时间码 | Paraformer V2 | Paraformer V1 | 状态 |", "|---|---|---|---|"])
    for row in comparison:
        lines.append(
            f"| {float(row['start']):.2f}-{float(row['end']):.2f} | {md_escape(row['primary'])} | "
            f"{md_escape(row['secondary'])} | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "`需复核`表示两模型不一致或背景音乐可能混入。必须结合可见字幕、口型和画面确认，不得直接当成角色对白。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare source identity, sampled frames and cross-checked Aliyun ASR evidence.")
    parser.add_argument("source", help="Local video path or public URL")
    parser.add_argument("--out-dir", required=True, help="Project evidence directory")
    parser.add_argument("--endpoint", help="Aliyun Bailian compatible-mode/v1 endpoint")
    parser.add_argument("--models", default="paraformer-v2,paraformer-v1")
    parser.add_argument("--resolution", type=int, default=768)
    parser.add_argument("--reversal", action="append", default=[], type=parse_range, metavar="START-END")
    args = parser.parse_args()

    if not WATCH_SCRIPT.exists():
        print(f"ERROR: watch backend missing: {WATCH_SCRIPT}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    local_media = None if is_url(args.source) else Path(args.source).expanduser().resolve()
    if local_media is not None and not local_media.is_file():
        print(f"ERROR: reference video not found: {local_media}", file=sys.stderr)
        return 2

    dotenv = read_dotenv(WATCH_CONFIG)
    api_key = setting("DASHSCOPE_API_KEY", dotenv)
    endpoint = args.endpoint or setting("DASHSCOPE_ENDPOINT", dotenv)
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not api_key or not endpoint:
        print(
            "ERROR: Aliyun ASR is not configured. Run scripts/configure_asr.py first; "
            "the key is never accepted as a command-line argument.",
            file=sys.stderr,
        )
        return 2
    if not models:
        print("ERROR: at least one ASR model is required", file=sys.stderr)
        return 2

    try:
        runs = {"全片": run_watch(args.source, out_dir / "watch" / "full", args.resolution)}
        runs["黄金三秒"] = run_watch(args.source, out_dir / "watch" / "hook", 1024, "0", "3")
        for index, (start, end) in enumerate(args.reversal, 1):
            runs[f"反转簇{index} {start}-{end}"] = run_watch(
                args.source, out_dir / "watch" / f"reversal_{index:02d}", 1024, start, end
            )
        if local_media is None:
            local_media = locate_downloaded_media(out_dir / "watch" / "full")
        manifest = source_manifest(args.source, local_media)
        runs["全片固定0.5秒时间线"] = extract_fixed_timeline(
            local_media,
            out_dir / "watch" / "timeline_0_5s",
            float(manifest["duration_seconds"]),
            args.resolution,
        )
        (out_dir / "00_source_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        audio_path = out_dir / "asr" / "audio_16k_mono.mp3"
        extract_audio(local_media, audio_path)
        transcripts = transcribe_models(audio_path, out_dir / "asr", api_key, endpoint, models)
        primary = transcripts.get("paraformer-v2") or next(iter(transcripts.values()))
        secondary = transcripts.get("paraformer-v1", [])
        comparison = compare_segments(primary, secondary)
        write_evidence_report(out_dir / "00_reference_evidence.md", manifest, runs, transcripts, comparison)
        (out_dir / "00_reference_evidence.json").write_text(
            json.dumps(
                {"source": manifest, "runs": runs, "transcripts": transcripts, "comparison": comparison},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except (RuntimeError, subprocess.CalledProcessError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    print(json.dumps({"status": "ok", "out_dir": str(out_dir), "source_sha256": manifest["sha256"], "frames": {k: v["frame_count"] for k, v in runs.items()}, "models": list(transcripts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
