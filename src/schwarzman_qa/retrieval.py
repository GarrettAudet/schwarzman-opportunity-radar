from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .citations import public_citation_ref
from .corpus import latest_file, load_chunks


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'/-]{1,}")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "can",
    "do",
    "does",
    "for",
    "from",
    "get",
    "have",
    "how",
    "i",
    "incoming",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "scholar",
    "scholars",
    "schwarzman",
    "should",
    "student",
    "students",
    "the",
    "there",
    "to",
    "we",
    "what",
    "where",
    "with",
    "you",
}
RAW_STOPWORDS = {"covers", "covered", "covering"}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    text = text.replace("_", " ")
    for raw in TOKEN_RE.findall(text):
        token = raw.lower().strip("_-/")
        if len(token) <= 1:
            continue
        if token in RAW_STOPWORDS:
            continue
        stem = simple_stem(token)
        if stem and stem not in STOPWORDS:
            tokens.append(stem)
    return tokens


def simple_stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def build_index(root: Path, chunks_path: Path | None = None) -> dict[str, Any]:
    if chunks_path is None:
        chunks_path = latest_file(root / "data" / "corpus" / "chunks", "corpus-chunks-*.jsonl")
    chunks = load_chunks(root, chunks_path)
    document_frequency: Counter[str] = Counter()
    indexed_chunks: list[dict[str, Any]] = []

    for chunk in chunks:
        text = chunk.get("text", "")
        source_file = public_citation_ref(chunk.get("source_file") or chunk.get("path"))
        citation_ref = public_citation_ref(chunk.get("citation_ref") or source_file)
        source_bits = " ".join(
            str(chunk.get(key, ""))
            for key in ("source_title", "source_file", "file_summary", "source")
        )
        counts = Counter(tokenize(f"{source_bits} {text}"))
        for token in counts:
            document_frequency[token] += 1
        indexed_chunks.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "source": chunk.get("source"),
                "source_file": source_file,
                "source_title": chunk.get("source_title", ""),
                "citation_ref": citation_ref,
                "chunk_index": chunk.get("chunk_index", 0),
                "char_start": chunk.get("char_start", 0),
                "char_end": chunk.get("char_end", 0),
                "review_decision": chunk.get("review_decision", ""),
                "qa_flags": chunk.get("qa_flags", ""),
                "file_summary": chunk.get("file_summary", ""),
                "text": text,
                "tokens": dict(counts),
                "length": sum(counts.values()) or 1,
            }
        )

    total = max(1, len(indexed_chunks))
    idf = {
        token: math.log((total + 1) / (df + 1)) + 1.0
        for token, df in document_frequency.items()
    }
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "chunks_path": str(chunks_path.relative_to(root)).replace("\\", "/"),
        "chunk_count": len(indexed_chunks),
        "idf": idf,
        "chunks": indexed_chunks,
    }


def save_index(root: Path, index: dict[str, Any]) -> Path:
    out_dir = root / "data" / "corpus" / "index"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_path = out_dir / f"local-index-{stamp}.json"
    out_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return out_path


def load_index(root: Path, index_path: Path | None = None) -> dict[str, Any]:
    if index_path is None:
        index_path = latest_file(root / "data" / "corpus" / "index", "local-index-*.json")
    return json.loads(index_path.read_text(encoding="utf-8"))


def retrieve(index: dict[str, Any], query: str, top_k: int = 6) -> list[dict[str, Any]]:
    query_counts = Counter(tokenize(query))
    if not query_counts:
        return []
    idf = index.get("idf", {})
    scored: list[tuple[float, dict[str, Any]]] = []
    query_terms = set(query_counts)

    for chunk in index.get("chunks", []):
        counts = chunk.get("tokens", {})
        score = 0.0
        for token, q_count in query_counts.items():
            tf = counts.get(token, 0)
            if not tf:
                continue
            score += (1 + math.log(tf)) * q_count * (idf.get(token, 1.0) ** 2)

        title_text = " ".join(
            str(chunk.get(key, "")).lower()
            for key in ("source_title", "source_file")
        )
        summary_text = str(chunk.get("file_summary", "")).lower()
        title_boost = sum(idf.get(token, 1.0) for token in query_terms if token in title_text)
        summary_boost = sum(idf.get(token, 1.0) for token in query_terms if token in summary_text)
        score = score / math.sqrt(chunk.get("length", 1))
        score += title_boost * 2.5
        score += summary_boost * 0.8
        if score > 0:
            result = {key: value for key, value in chunk.items() if key != "tokens"}
            source_file = public_citation_ref(result.get("source_file") or result.get("path"))
            result["source_file"] = source_file
            result["citation_ref"] = public_citation_ref(result.get("citation_ref") or source_file)
            result["score"] = round(score, 6)
            scored.append((score, result))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in scored[:top_k]]
