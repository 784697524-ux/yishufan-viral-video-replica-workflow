#!/usr/bin/env python3
"""Build and query the local ArtFan viral-video vector library."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import struct
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = Path.cwd()
DEFAULT_CHAT_ROOT = Path.home() / ".codex"
DEFAULT_SEED_INDEX = SKILL_DIR / "knowledge_base" / "index.sqlite3"
VECTOR_DIM = 2048
MAX_FILE_BYTES = 2_000_000
CHUNK_CHARS = 6000

TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv"}
VIDEO_TERMS = (
    "艺术犯", "艺术范", "爆款", "复刻", "拉片", "分镜", "脚本", "镜头", "反转",
    "seedance", "短视频", "秦始皇", "梵高", "蒙娜丽莎", "唐俑", "宋韵", "眼儿媚",
    "蟠桃宴", "盗墓", "周瑜", "小乔", "名画", "商品植入", "完播率",
)
SKIP_CHAT_PREFIXES = (
    "<app-context>", "<skills_instructions>", "<recommended_plugins>",
    "# AGENTS.md instructions", "<environment_context>", "<permissions instructions>",
)

TAXONOMY = {
    "名画油画": ("名画", "油画", "画中", "蒙娜丽莎", "梵高", "伦勃朗", "古典绘画"),
    "东方古装": ("古装", "宋韵", "唐俑", "秦始皇", "周瑜", "小乔", "天宫", "仙侠", "古代"),
    "历史CG": ("历史cg", "历史", "秦始皇", "兵马俑", "帝王"),
    "盗墓奇幻": ("盗墓", "盗笔", "古墓", "墓室"),
    "奇幻冒险": ("奇幻", "冒险", "闯关", "幻境"),
    "现代商场": ("商场", "银泰", "百货", "购物中心", "逛吃"),
    "聊天体": ("微信", "聊天记录", "群聊", "对话框"),
    "情侣约会": ("情侣", "约会", "求爱", "告白", "追求", "双人", "恋爱"),
    "竞争关系": ("竞争", "擂台", "对手", "争夺", "二选一", "抢"),
    "闺蜜群像": ("闺蜜", "姐妹", "群像", "三人", "多人"),
    "亲子家庭": ("亲子", "家庭", "孩子", "儿童", "父母"),
    "职场权力": ("职场", "老板", "下属", "甲方", "领导", "权力"),
    "双人餐饮": ("双人餐", "餐饮", "吃饭", "美食", "牛排", "火锅", "面包"),
    "观影娱乐": ("电影", "观影", "影城", "影院", "游戏", "游戏币"),
    "饮品奶茶": ("饮品", "奶茶", "咖啡", "喝", "口渴"),
    "美妆护理": ("美妆", "护肤", "护理", "按摩", "眼镜", "体验装"),
    "综合权益卡": ("权益卡", "逛吃卡", "光之卡", "亲子卡", "周末卡", "卡券", "套餐", "多选", "任选", "资格券"),
    "低价反差": ("125元", "158元", "低价", "价格", "预算", "便宜", "秒杀", "高价误判"),
    "异常钩子": ("异常", "黄金三秒", "前三秒", "钩子", "反常", "抓眼"),
    "身份错位": ("身份错位", "误认", "误判", "冒充", "错位"),
    "权力反转": ("权力反转", "反客为主", "压制", "地位反转", "翻身"),
    "道具变义": ("道具", "礼物", "卡", "变义", "揭示", "筹码"),
    "空间揭示": ("空间揭示", "画中画", "门后", "镜头拉开", "真相揭示"),
    "循环结尾": ("循环", "首尾呼应", "回扣", "结尾记忆点"),
    "价格反转": ("价格反转", "预算危机", "高价误判", "原来只要", "只要125"),
    "追逃抓包": ("追逃", "追逐", "抓包", "被发现", "逃跑"),
    "选择冲突": ("选择冲突", "二选一", "选谁", "评论区", "替角色决定"),
    "高保真": ("高保真", "逐镜", "视觉复刻"),
    "机制迁移": ("机制迁移", "传播机制", "机制dna"),
    "商业混合": ("商业混合", "商品植入", "商业复刻"),
}

TAG_GROUPS = (
    {"名画油画", "东方古装", "历史CG", "盗墓奇幻", "奇幻冒险", "现代商场", "聊天体"},
    {"情侣约会", "竞争关系", "闺蜜群像", "亲子家庭", "职场权力"},
    {"双人餐饮", "观影娱乐", "饮品奶茶", "美妆护理", "综合权益卡", "低价反差"},
)

SECRET_PATTERNS = (
    re.compile(r"\b(?:gsk|sk)[_-][A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*[^\s,;]+"),
)
PORTABLE_ID_PATTERN = re.compile(
    r"(?i)([\"']?(?:file[_ -]?token|app[_ -]?token|access[_ -]?token|base[_ -]?id|"
    r"table[_ -]?id|record[_ -]?id|field[_ -]?id)[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9_-]{6,})"
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def portable_text(text: str) -> str:
    text = redact(text)
    text = re.sub(r"/Users/[^/\s]+", "<USER_HOME>", text)
    text = re.sub(r"/home/[^/\s]+", "<USER_HOME>", text)
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "<USER_HOME>", text)
    text = text.replace("/Users/", "<USER_HOME>/").replace("/home/", "<USER_HOME>/")
    text = PORTABLE_ID_PATTERN.sub(r"\1[REDACTED]", text)
    return EMAIL_PATTERN.sub("[EMAIL_REDACTED]", text)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def extract_tags(text: str) -> list[str]:
    lowered = normalize(text)
    return [tag for tag, terms in TAXONOMY.items() if any(term.lower() in lowered for term in terms)]


def _features(text: str, tags: list[str]) -> Counter[str]:
    cleaned = re.sub(r"[^\u4e00-\u9fff0-9a-z]+", " ", normalize(text))
    features: Counter[str] = Counter()
    for word in re.findall(r"[a-z0-9]+", cleaned):
        features[f"w:{word}"] += 1.5
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", cleaned))
    for n, weight in ((2, 1.0), (3, 0.7)):
        for i in range(max(0, len(chinese) - n + 1)):
            features[f"c{n}:{chinese[i:i+n]}"] += weight
    for tag in tags:
        features[f"tag:{tag}"] += 5.0
    return features


def vectorize(text: str, tags: list[str]) -> list[float]:
    vector = [0.0] * VECTOR_DIM
    for feature, count in _features(text, tags).items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % VECTOR_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * math.log1p(count)
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{VECTOR_DIM}f", *vector)


def unpack_vector(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{VECTOR_DIM}f", blob)


def cosine(left: list[float], right_blob: bytes) -> float:
    return sum(a * b for a, b in zip(left, unpack_vector(right_blob)))


def classify_file(path: Path) -> str:
    name = path.name.lower()
    if re.search(r"qc|review|quality|gate|director|复盘|验收|compare|差距|问题", name):
        return "qc_review"
    if re.search(r"prompt|seedance|提示词", name):
        return "prompt"
    if re.search(r"(?:^|[_-])script(?:[_\-.]|$)|脚本|screenplay", name):
        return "script"
    if re.search(r"storyboard|分镜|shot", name):
        return "storyboard"
    if re.search(r"reference|evidence|analysis|00_source_manifest|拉片|机制|pixel|model", name):
        return "reference_analysis"
    if re.search(r"facts|商品|权益", name):
        return "product_facts"
    if re.search(r"contract|mapping|映射", name):
        return "contract"
    return "other"


def read_text(path: Path) -> str:
    if path.stat().st_size > MAX_FILE_BYTES:
        return ""
    try:
        return redact(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return ""


def chunks(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]


def relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def infer_quality(qc_text: str) -> str:
    lowered = qc_text.lower()
    if "block_publish" in lowered or "block_stitch" in lowered or "禁止发布" in qc_text:
        return "blocked"
    if "allow_publish" in lowered:
        return "allow_publish"
    if "allow_stitch" in lowered:
        return "allow_stitch"
    if "allow_generation" in lowered:
        return "allow_generation"
    if "不建议发布" in qc_text or "未通过" in qc_text:
        return "needs_review"
    return "unknown"


def extract_source_info(text: str) -> tuple[str, str]:
    videos = re.findall(r"/[^\n\r\"'`]+\.mp4", text, flags=re.I)
    sha = re.search(r"\b[a-f0-9]{64}\b", text, flags=re.I)
    return (videos[0] if videos else "", sha.group(0).lower() if sha else "")


def root_source_info(root: Path) -> tuple[str, str]:
    manifest = root / "00_source_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            source = data.get("resolved_media") or data.get("requested_source") or data.get("source_path") or ""
            sha = data.get("sha256") or ""
            if source or sha:
                return str(source), str(sha).lower()
        except (OSError, json.JSONDecodeError):
            pass
    source_docs = []
    for filename in ("00_reference_evidence.json", "00_reference_evidence.md", "01_reference_analysis.md"):
        path = root / filename
        if path.exists():
            source_docs.append(read_text(path))
    return extract_source_info("\n".join(source_docs))


def portable_asset_path(value: str, case_root: Path, case_id: str) -> str:
    if not value:
        return ""
    path = Path(value)
    try:
        relative = path.relative_to(case_root)
        return f"case://{case_id}/{relative.as_posix()}"
    except ValueError:
        return f"case://{case_id}/{path.name}"


def make_portable(cases: list[dict], documents: list[dict]) -> None:
    roots = {case["case_id"]: Path(case["root_path"]) for case in cases}
    for case in cases:
        case_id = case["case_id"]
        root = roots[case_id]
        for key in ("analysis_files", "script_files", "prompt_files", "storyboard_files", "qc_files"):
            case[key] = [portable_asset_path(path, root, case_id) for path in case[key]]
        case["root_path"] = f"case://{case_id}"
        case["source_video_path"] = f"sha256://{case['source_sha256']}" if case["source_sha256"] else ""
        case["source_video_available"] = False
        case["source_kind"] = "seed_case"
    for document in documents:
        case_id = document["case_id"]
        document["path"] = portable_asset_path(document["path"], roots[case_id], case_id)
        document["text"] = portable_text(document["text"])


def output_cases(workspace: Path, portable: bool = False) -> tuple[list[dict], list[dict]]:
    cases: list[dict] = []
    documents: list[dict] = []
    outputs = workspace / "outputs"
    if not outputs.exists():
        return cases, documents
    for root in sorted(path for path in outputs.iterdir() if path.is_dir()):
        selected: list[tuple[Path, str, str]] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            doc_type = classify_file(path)
            if doc_type == "other" and path.name not in {"README.md", "final_report.md"}:
                continue
            text = read_text(path)
            if portable:
                text = portable_text(text)
            if text and any(term.lower() in text.lower() for term in VIDEO_TERMS):
                selected.append((path, doc_type, text))
        if not selected:
            continue

        combined = "\n".join(text[:25000] for _, _, text in selected)
        qc_text = "\n".join(text for _, kind, text in selected if kind == "qc_review")
        source_path, source_sha = root_source_info(root)
        case_id = "output_" + hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:16]
        paths_by_type: dict[str, list[str]] = defaultdict(list)
        for path, doc_type, text in selected:
            paths_by_type[doc_type].append(str(path))
            for index, chunk in enumerate(chunks(text), start=1):
                tags = extract_tags(f"{root.name}\n{chunk}")
                documents.append({
                    "doc_id": f"{case_id}_{hashlib.sha1(str(path).encode()).hexdigest()[:10]}_{index}",
                    "case_id": case_id,
                    "doc_type": doc_type,
                    "path": str(path),
                    "title": f"{root.name} / {path.name} / {index}",
                    "text": chunk,
                    "weight": {"reference_analysis": 1.0, "script": 0.9, "storyboard": 0.9,
                               "prompt": 0.85, "qc_review": 0.8, "product_facts": 0.75,
                               "contract": 0.8}.get(doc_type, 0.6),
                    "tags": tags,
                })

        storyboard_assets = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            lowered = str(path).lower()
            basename = path.name.lower()
            generated_qc_frame = any(part in lowered for part in (
                "/watch/", "reference_frames", "candidate_frames", "uniform_frames",
                "hook_frames", "timeline_", "final_render_asr"
            ))
            asset_hint = (
                "storyboard" in lowered or "分镜" in lowered or "character" in lowered
                or re.search(r"(?:^|[_-])shot\d*", basename)
                or re.search(r"(?:^|[_-])b\d{2}(?:[_\-.]|$)", basename)
            )
            if not generated_qc_frame and asset_hint:
                storyboard_assets.append(str(path))
        quality = infer_quality(qc_text)
        tags = extract_tags(f"{root.name}\n{combined}")
        cases.append({
            "case_id": case_id,
            "title": root.name,
            "root_path": str(root),
            "source_video_path": source_path,
            "source_video_available": bool(source_path and Path(source_path).exists()),
            "source_sha256": source_sha,
            "quality_status": quality,
            "tags": tags,
            "analysis_files": paths_by_type["reference_analysis"],
            "script_files": paths_by_type["script"],
            "prompt_files": paths_by_type["prompt"],
            "storyboard_files": paths_by_type["storyboard"] + storyboard_assets[:80],
            "qc_files": paths_by_type["qc_review"],
            "source_kind": "workspace_output",
        })
    return cases, documents


def extract_message(payload: dict) -> tuple[str, str]:
    if payload.get("type") != "message":
        return "", ""
    role = payload.get("role", "")
    parts = []
    for item in payload.get("content", []):
        if isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"}:
            parts.append(item.get("text", ""))
    return role, "\n".join(parts)


def chat_cases(workspace: Path, chat_root: Path) -> tuple[list[dict], list[dict]]:
    cases: list[dict] = []
    documents: list[dict] = []
    session_files = list((chat_root / "archived_sessions").glob("*.jsonl"))
    session_files += list((chat_root / "sessions").rglob("*.jsonl"))
    seen_ids: set[str] = set()
    for session_file in sorted(session_files):
        session_id = ""
        session_cwd = ""
        messages: list[tuple[str, str]] = []
        try:
            with session_file.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "session_meta":
                        session_id = event.get("payload", {}).get("id", "")
                        session_cwd = event.get("payload", {}).get("cwd", "")
                    elif event.get("type") == "response_item":
                        role, text = extract_message(event.get("payload", {}))
                        normalized = text.strip()
                        if not normalized or normalized.startswith(SKIP_CHAT_PREFIXES):
                            continue
                        if any(term.lower() in normalized.lower() for term in VIDEO_TERMS):
                            messages.append((role, redact(normalized[:24000])))
        except OSError:
            continue
        if Path(session_cwd) != workspace or not messages or session_id in seen_ids:
            continue
        seen_ids.add(session_id)
        case_id = f"chat_{session_id}"
        first_user = next((text for role, text in messages if role == "user"), messages[0][1])
        title = re.sub(r"\s+", " ", first_user)[:70]
        combined = "\n".join(text for _, text in messages)
        for index, (role, text) in enumerate(messages, start=1):
            tags = extract_tags(text)
            documents.append({
                "doc_id": f"{case_id}_{index}",
                "case_id": case_id,
                "doc_type": "chat_history",
                "path": str(session_file),
                "title": f"{title} / {role} / {index}",
                "text": text,
                "weight": 0.5,
                "tags": tags,
            })
        cases.append({
            "case_id": case_id,
            "title": f"历史聊天：{title}",
            "root_path": str(session_file),
            "source_video_path": extract_source_info(combined)[0],
            "source_video_available": False,
            "source_sha256": extract_source_info(combined)[1],
            "quality_status": infer_quality(combined),
            "tags": extract_tags(combined),
            "analysis_files": [], "script_files": [], "prompt_files": [],
            "storyboard_files": [], "qc_files": [],
            "source_kind": "codex_chat",
        })
    return cases, documents


def init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY, title TEXT NOT NULL, root_path TEXT NOT NULL,
            source_video_path TEXT, source_video_available INTEGER NOT NULL,
            source_sha256 TEXT, quality_status TEXT NOT NULL, tags_json TEXT NOT NULL,
            analysis_files_json TEXT NOT NULL, script_files_json TEXT NOT NULL,
            prompt_files_json TEXT NOT NULL, storyboard_files_json TEXT NOT NULL,
            qc_files_json TEXT NOT NULL, source_kind TEXT NOT NULL
        );
        CREATE TABLE documents (
            doc_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, doc_type TEXT NOT NULL,
            path TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
            weight REAL NOT NULL, tags_json TEXT NOT NULL, vector BLOB NOT NULL
        );
        CREATE INDEX documents_case_id ON documents(case_id);
    """)


def import_seed(connection: sqlite3.Connection, seed_index: Path | None) -> tuple[int, int]:
    if not seed_index or not seed_index.is_file():
        return 0, 0
    source = sqlite3.connect(f"file:{seed_index.resolve()}?mode=ro", uri=True)
    try:
        schema = source.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not schema or schema[0] not in {"1", "2"}:
            raise ValueError(f"unsupported seed schema: {schema[0] if schema else 'missing'}")
        case_rows = list(source.execute("SELECT * FROM cases"))
        document_rows = list(source.execute("SELECT * FROM documents"))
    finally:
        source.close()
    connection.executemany("INSERT OR IGNORE INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", case_rows)
    connection.executemany("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?,?)", document_rows)
    return len(case_rows), len(document_rows)


def catalog_markdown(rows: list[tuple]) -> str:
    lines = [
        "# 艺术范爆款案例库目录",
        "",
        "| 案例 | 质量状态 | 来源 | 机制标签 |",
        "|---|---|---|---|",
    ]
    for title, quality, source_kind, tags_json in rows:
        tags = "、".join(json.loads(tags_json)) or "未分类"
        safe_title = title.replace("|", "\\|")
        lines.append(f"| {safe_title} | {quality} | {source_kind} | {tags} |")
    lines.append("")
    return "\n".join(lines)


def build_library(
    workspace: Path,
    library_dir: Path,
    chat_root: Path,
    include_chats: bool,
    seed_index: Path | None = None,
    portable: bool = False,
) -> dict:
    cases, documents = output_cases(workspace, portable=portable)
    if include_chats:
        extra_cases, extra_documents = chat_cases(workspace, chat_root)
        cases.extend(extra_cases)
        documents.extend(extra_documents)
    workspace_case_count = sum(case["source_kind"] == "workspace_output" for case in cases)
    chat_case_count = sum(case["source_kind"] == "codex_chat" for case in cases)
    if portable:
        if include_chats:
            raise ValueError("portable libraries cannot include chat history")
        make_portable(cases, documents)
    library_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="viral-index-", suffix=".sqlite3", dir=library_dir, delete=False) as temp:
        temp_path = Path(temp.name)
    connection = sqlite3.connect(temp_path)
    try:
        init_schema(connection)
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", "2"))
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("vector_model", f"local-hash-zh-{VECTOR_DIM}"))
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("portable", str(portable).lower()))
        seed_case_count, seed_document_count = import_seed(connection, seed_index)
        for case in cases:
            connection.execute(
                "INSERT OR REPLACE INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (case["case_id"], case["title"], case["root_path"], case["source_video_path"],
                 int(case["source_video_available"]), case["source_sha256"], case["quality_status"],
                 json.dumps(case["tags"], ensure_ascii=False),
                 json.dumps(case["analysis_files"], ensure_ascii=False),
                 json.dumps(case["script_files"], ensure_ascii=False),
                 json.dumps(case["prompt_files"], ensure_ascii=False),
                 json.dumps(case["storyboard_files"], ensure_ascii=False),
                 json.dumps(case["qc_files"], ensure_ascii=False), case["source_kind"]),
            )
        for doc in documents:
            vector = vectorize(f"{doc['title']}\n{doc['text']}", doc["tags"])
            connection.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?,?)",
                (doc["doc_id"], doc["case_id"], doc["doc_type"], doc["path"], doc["title"],
                 doc["text"], doc["weight"], json.dumps(doc["tags"], ensure_ascii=False),
                 pack_vector(vector)),
            )
        connection.commit()
        total_case_count = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        total_document_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        blocked_case_count = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE quality_status='blocked'"
        ).fetchone()[0]
        catalog_rows = list(connection.execute(
            "SELECT title,quality_status,source_kind,tags_json FROM cases ORDER BY title"
        ))
    finally:
        connection.close()
    target = library_dir / "index.sqlite3"
    temp_path.replace(target)
    summary = {
        "schema_version": 2,
        "vector_model": f"local-hash-zh-{VECTOR_DIM}",
        "portable": portable,
        "workspace": "<PORTABLE_SOURCE>" if portable else str(workspace),
        "index": "index.sqlite3" if portable else str(target),
        "case_count": total_case_count,
        "document_count": total_document_count,
        "workspace_case_count": workspace_case_count,
        "chat_case_count": chat_case_count,
        "seed_case_count": seed_case_count,
        "seed_document_count": seed_document_count,
        "blocked_case_count": blocked_case_count,
    }
    (library_dir / "catalog.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (library_dir / "catalog.md").write_text(catalog_markdown(catalog_rows), encoding="utf-8")
    return summary


def load_cases(connection: sqlite3.Connection) -> dict[str, dict]:
    columns = [row[1] for row in connection.execute("PRAGMA table_info(cases)")]
    result = {}
    for row in connection.execute("SELECT * FROM cases"):
        case = dict(zip(columns, row))
        for key in ("tags_json", "analysis_files_json", "script_files_json", "prompt_files_json",
                    "storyboard_files_json", "qc_files_json"):
            case[key[:-5]] = json.loads(case.pop(key))
        case["source_video_available"] = bool(case["source_video_available"])
        result[case["case_id"]] = case
    return result


def search_library(index: Path, query: str, top_k: int = 5) -> dict:
    connection = sqlite3.connect(index)
    try:
        cases = load_cases(connection)
        query_tags = extract_tags(query)
        query_vector = vectorize(query, query_tags)
        per_case: dict[str, list[dict]] = defaultdict(list)
        for doc_id, case_id, doc_type, path, title, text, weight, tags_json, blob in connection.execute(
            "SELECT doc_id,case_id,doc_type,path,title,text,weight,tags_json,vector FROM documents"
        ):
            tags = json.loads(tags_json)
            union = set(tags) | set(query_tags)
            overlap = len(set(tags) & set(query_tags)) / len(union) if union else 0.0
            score = 0.74 * max(0.0, cosine(query_vector, blob)) + 0.18 * overlap + 0.08 * weight
            if doc_type == "chat_history":
                score -= 0.12
            per_case[case_id].append({
                "doc_id": doc_id, "doc_type": doc_type, "path": path, "title": title,
                "score": round(score, 6), "matched_tags": sorted(set(tags) & set(query_tags)),
                "excerpt": re.sub(r"\s+", " ", text).strip()[:500],
            })
    finally:
        connection.close()

    recommendations = []
    negative_lessons = []
    for case_id, hits in per_case.items():
        hits.sort(key=lambda item: item["score"], reverse=True)
        case = cases[case_id]
        best = hits[0]
        constraint_adjustment = 0.0
        for group in TAG_GROUPS:
            requested = set(query_tags) & group
            if not requested:
                continue
            matched = requested & set(case["tags"])
            constraint_adjustment += 0.05 * (len(matched) / len(requested)) if matched else -0.10
        adjusted_score = max(0.0, best["score"] + constraint_adjustment)
        has_reference = any(hit["doc_type"] == "reference_analysis" for hit in hits[:8])
        blocked = case["quality_status"] == "blocked"
        if blocked and not has_reference:
            reuse_scope = "negative_lessons_only"
        elif blocked:
            reuse_scope = "reference_analysis_only"
        else:
            reuse_scope = "analysis_script_storyboard"
        item = {
            "case_id": case_id,
            "title": case["title"],
            "score": round(adjusted_score, 6),
            "matched_tags": sorted(set(case["tags"]) & set(query_tags)),
            "quality_status": case["quality_status"],
            "reuse_scope": reuse_scope,
            "source_kind": case["source_kind"],
            "root_path": case["root_path"],
            "source_video_path": case["source_video_path"],
            "source_video_available": case["source_video_available"],
            "analysis_files": case["analysis_files"],
            "script_files": case["script_files"] if reuse_scope == "analysis_script_storyboard" else [],
            "prompt_files": case["prompt_files"] if reuse_scope == "analysis_script_storyboard" else [],
            "storyboard_files": case["storyboard_files"] if reuse_scope == "analysis_script_storyboard" else [],
            "matched_documents": hits[:3],
        }
        if reuse_scope != "negative_lessons_only":
            recommendations.append(item)
        qc_hits = [hit for hit in hits if hit["doc_type"] == "qc_review"]
        if blocked and qc_hits:
            negative_lessons.append({
                "title": case["title"], "score": qc_hits[0]["score"],
                "quality_status": case["quality_status"], "qc_files": case["qc_files"],
                "matched_document": qc_hits[0],
            })
    recommendations.sort(key=lambda item: item["score"], reverse=True)
    negative_lessons.sort(key=lambda item: item["score"], reverse=True)
    recommendations = recommendations[:top_k]
    production_template = next(
        (item for item in recommendations
         if item["reuse_scope"] == "analysis_script_storyboard"
         and item["source_kind"] in {"workspace_output", "seed_case"}
         and (item["script_files"] or item["storyboard_files"])),
        None,
    )
    return {
        "query": query,
        "query_tags": query_tags,
        "decision": "matched" if recommendations and recommendations[0]["score"] >= 0.12 else "insufficient_match",
        "main_reference": recommendations[0] if recommendations else None,
        "production_template": production_template,
        "alternatives": recommendations[1:top_k],
        "negative_lessons": negative_lessons[:3],
        "rule": "blocked案例只可复用原片分析或失败教训，不得复用其未通过脚本、提示词和分镜。",
    }


def render_markdown(result: dict) -> str:
    lines = ["# 历史爆款智能匹配报告", "", f"- 需求：{result['query']}",
             f"- 识别标签：{'、'.join(result['query_tags']) or '未识别'}",
             f"- 决策：{result['decision']}", ""]
    if result["production_template"]:
        lines += ["## 可复用生产模板", "",
                  f"- {result['production_template']['title']}",
                  f"- 允许复用：{result['production_template']['reuse_scope']}", ""]
    recommendations = [result["main_reference"]] + result["alternatives"] if result["main_reference"] else []
    lines += ["## 推荐参考", ""]
    for index, item in enumerate(recommendations, start=1):
        lines += [f"### {index}. {item['title']}", "",
                  f"- 匹配分：{item['score']:.3f}",
                  f"- 命中机制：{'、'.join(item['matched_tags']) or '语义相似'}",
                  f"- 质量状态：{item['quality_status']}",
                  f"- 允许复用：{item['reuse_scope']}",
                  f"- 原视频当前可用：{'是' if item['source_video_available'] else '否'}",
                  f"- 案例目录：`{item['root_path']}`"]
        for label, key in (("分析", "analysis_files"), ("脚本", "script_files"),
                           ("提示词", "prompt_files"), ("分镜", "storyboard_files")):
            if item[key]:
                lines.append(f"- {label}资产：")
                lines += [f"  - `{path}`" for path in item[key][:8]]
        if item["matched_documents"]:
            lines.append("- 命中内容摘录：")
            for hit in item["matched_documents"]:
                lines.append(f"  - {hit['doc_type']}｜{hit['excerpt']}")
        lines.append("")
    lines += ["## 必须吸取的失败教训", ""]
    if not result["negative_lessons"]:
        lines.append("- 本次没有召回高相关的失败案例。")
    for item in result["negative_lessons"]:
        lines += [f"- {item['title']}（{item['quality_status']}，匹配分 {item['score']:.3f}）"]
        lines += [f"  - `{path}`" for path in item["qc_files"][:6]]
    lines += ["", f"> {result['rule']}", ""]
    return "\n".join(lines)


def show_case(index: Path, case_id: str) -> dict:
    connection = sqlite3.connect(index)
    try:
        cases = load_cases(connection)
        if case_id not in cases:
            raise KeyError(case_id)
        documents = []
        for doc_type, path, title, text, tags_json in connection.execute(
            "SELECT doc_type,path,title,text,tags_json FROM documents WHERE case_id=? ORDER BY doc_type,title",
            (case_id,),
        ):
            documents.append({
                "doc_type": doc_type,
                "path": path,
                "title": title,
                "text": text,
                "tags": json.loads(tags_json),
            })
    finally:
        connection.close()
    return {"case": cases[case_id], "documents": documents}


def render_case_markdown(result: dict) -> str:
    case = result["case"]
    lines = [
        f"# {case['title']}",
        "",
        f"- 案例 ID：`{case['case_id']}`",
        f"- 质量状态：{case['quality_status']}",
        f"- 可复用范围：{'reference_analysis_only' if case['quality_status'] == 'blocked' else 'analysis_script_storyboard'}",
        f"- 机制标签：{'、'.join(case['tags']) or '未分类'}",
        "",
    ]
    for document in result["documents"]:
        lines.extend([
            f"## {document['doc_type']}｜{document['title']}",
            "",
            document["text"],
            "",
        ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build or refresh the local library")
    build.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    build.add_argument("--library-dir", type=Path)
    build.add_argument("--chat-root", type=Path, default=DEFAULT_CHAT_ROOT)
    build.add_argument("--include-chats", action="store_true", help="Include private Codex chats in a local-only index")
    build.add_argument("--no-chats", action="store_true", help=argparse.SUPPRESS)
    build.add_argument("--seed-index", type=Path)
    build.add_argument("--no-seed", action="store_true")
    build.add_argument("--portable", action="store_true", help="Create a share-safe index without chats or local paths")
    search = subparsers.add_parser("search", help="Search by product and creative brief")
    search.add_argument("query")
    search.add_argument("--index", type=Path)
    search.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--out", type=Path)
    search.add_argument("--json", action="store_true")
    show = subparsers.add_parser("show", help="Read the archived text for one matched case")
    show.add_argument("case_id")
    show.add_argument("--index", type=Path)
    show.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    show.add_argument("--out", type=Path)
    show.add_argument("--json", action="store_true")
    return parser.parse_args()


def resolve_index(index: Path | None, workspace: Path) -> Path:
    if index:
        return index.expanduser().resolve()
    local_index = workspace.expanduser().resolve() / "viral_library" / "index.sqlite3"
    if local_index.is_file():
        return local_index
    if DEFAULT_SEED_INDEX.is_file():
        return DEFAULT_SEED_INDEX
    return local_index


def main() -> int:
    args = parse_args()
    if args.command == "build":
        library_dir = args.library_dir or args.workspace / "viral_library"
        include_chats = args.include_chats and not args.no_chats and not args.portable
        seed_index = None if args.no_seed else (args.seed_index or DEFAULT_SEED_INDEX)
        result = build_library(
            args.workspace.resolve(),
            library_dir.resolve(),
            args.chat_root.resolve(),
            include_chats,
            seed_index=seed_index,
            portable=args.portable,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    index = resolve_index(args.index, args.workspace)
    if not index.exists():
        raise SystemExit(f"索引不存在，请先运行 build：{index}")
    if args.command == "search":
        result = search_library(index, args.query, max(1, args.top_k))
        rendered = json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_markdown(result)
    else:
        try:
            result = show_case(index, args.case_id)
        except KeyError:
            raise SystemExit(f"案例不存在：{args.case_id}") from None
        rendered = json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_case_markdown(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
