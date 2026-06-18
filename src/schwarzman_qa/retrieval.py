from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
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
RAW_STOPWORDS = {"cover", "covers", "covered", "covering"}
QUERY_SYNONYMS = {
    "meet": ["webinar", "session", "call"],
    "meeting": ["webinar", "session", "call"],
    "webinar": ["meeting", "session", "call"],
    "session": ["meeting", "webinar", "call"],
    "todo": ["to-do", "task", "deadline", "action"],
    "to-do": ["todo", "task", "deadline", "action"],
    "task": ["to-do", "todo", "deadline", "action"],
    "permit": ["visa", "residence", "stay"],
    "residence": ["permit", "stay", "visa"],
    "rent": ["apartment", "housing"],
    "rental": ["apartment", "housing"],
    "apartment": ["rent", "rental", "housing"],
    "housing": ["apartment", "rent", "rental", "dorm"],
    "mandarin": ["chinese", "language"],
    "wechat": ["weixin"],
}


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    tokens: list[str] = []
    text = text.replace("_", " ")
    for raw in TOKEN_RE.findall(text):
        token = raw.lower().strip("_-/")
        if len(token) <= 1:
            continue
        if token in RAW_STOPWORDS:
            continue
        stem = simple_stem(token)
        if stem and (keep_stopwords or stem not in STOPWORDS):
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
                "title_tokens": dict(Counter(tokenize(chunk.get("source_title", ""), keep_stopwords=True))),
                "path_tokens": dict(Counter(tokenize(source_file, keep_stopwords=True))),
                "summary_tokens": dict(Counter(tokenize(chunk.get("file_summary", ""), keep_stopwords=True))),
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
    query_counts = expanded_query_counts(query)
    if not query_counts:
        return []
    idf = index.get("idf", {})
    scored: list[tuple[float, dict[str, Any]]] = []

    for chunk in index.get("chunks", []):
        score, reasons = score_chunk(index, chunk, query, query_counts)
        if score > 0:
            result = {key: value for key, value in chunk.items() if key != "tokens"}
            source_file = public_citation_ref(result.get("source_file") or result.get("path"))
            result["source_file"] = source_file
            result["citation_ref"] = public_citation_ref(result.get("citation_ref") or source_file)
            result["score"] = round(score, 6)
            if reasons:
                result["match_reasons"] = reasons
            scored.append((score, result))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in scored[:top_k]]


def expanded_query_counts(query: str) -> Counter[str]:
    counts: Counter[str] = Counter(tokenize(query))
    for token, count in list(counts.items()):
        for synonym in QUERY_SYNONYMS.get(token, []):
            for expanded in tokenize(synonym):
                counts[expanded] += count * 0.65
    return counts


def score_chunk(
    index: dict[str, Any],
    chunk: dict[str, Any],
    query: str,
    query_counts: Counter[str],
) -> tuple[float, list[str]]:
    idf = index.get("idf", {})
    reasons: list[str] = []

    counts = chunk.get("tokens", {})
    content_score = weighted_token_score(query_counts, counts, idf)
    if content_score:
        content_score = content_score / math.sqrt(chunk.get("length", 1))
        reasons.append("content")

    title_counts = field_counts(chunk, "title_tokens", str(chunk.get("source_title", "")))
    path_counts = field_counts(chunk, "path_tokens", str(chunk.get("source_file", "")))
    summary_counts = field_counts(chunk, "summary_tokens", str(chunk.get("file_summary", "")))
    title_score = field_overlap_score(query_counts, title_counts, idf, weight=4.5)
    path_score = field_overlap_score(query_counts, path_counts, idf, weight=2.5)
    summary_score = field_overlap_score(query_counts, summary_counts, idf, weight=1.2)

    title_text = normalize_match_text(f"{chunk.get('source_title', '')} {chunk.get('source_file', '')}")
    summary_text = normalize_match_text(str(chunk.get("file_summary", "")))
    query_text = normalize_match_text(query)
    phrase_score = phrase_match_score(query_text, title_text, weight=8.0)
    fuzzy_score = fuzzy_title_score(query_text, title_text)
    if title_score or phrase_score or fuzzy_score:
        reasons.append("title")
    if summary_score:
        reasons.append("summary")
    if path_score:
        reasons.append("path")

    return content_score + title_score + path_score + summary_score + phrase_score + fuzzy_score, reasons


def weighted_token_score(query_counts: Counter[str], counts: dict[str, float], idf: dict[str, float]) -> float:
    score = 0.0
    for token, q_count in query_counts.items():
        tf = counts.get(token, 0)
        if not tf:
            continue
        score += (1 + math.log(tf)) * q_count * (idf.get(token, 1.0) ** 2)
    return score


def field_counts(chunk: dict[str, Any], token_key: str, fallback_text: str) -> Counter[str]:
    existing = chunk.get(token_key)
    if isinstance(existing, dict) and existing:
        return Counter(existing)
    return Counter(tokenize(fallback_text, keep_stopwords=True))


def field_overlap_score(
    query_counts: Counter[str],
    field_token_counts: Counter[str],
    idf: dict[str, float],
    *,
    weight: float,
) -> float:
    score = 0.0
    for token, q_count in query_counts.items():
        if token in field_token_counts:
            score += q_count * idf.get(token, 1.0)
    return score * weight


def normalize_match_text(text: str) -> str:
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def phrase_match_score(query_text: str, field_text: str, *, weight: float) -> float:
    if not query_text or not field_text:
        return 0.0
    query_tokens = [token for token in tokenize(query_text, keep_stopwords=True) if token not in RAW_STOPWORDS]
    field_tokens = set(tokenize(field_text, keep_stopwords=True))
    score = 0.0
    for size in (4, 3, 2):
        for index in range(0, max(0, len(query_tokens) - size + 1)):
            gram = query_tokens[index : index + size]
            if all(token in field_tokens for token in gram):
                score += weight * size
    return score


def fuzzy_title_score(query_text: str, title_text: str) -> float:
    if len(query_text) < 12 or len(title_text) < 12:
        return 0.0
    ratio = SequenceMatcher(None, query_text, title_text).ratio()
    return 12.0 * ratio if ratio >= 0.42 else 0.0


def document_candidates(index: dict[str, Any], query: str, top_k: int = 8) -> list[dict[str, Any]]:
    query_counts = expanded_query_counts(query)
    if not query_counts:
        return []
    docs: dict[str, dict[str, Any]] = {}
    for chunk in index.get("chunks", []):
        ref = public_citation_ref(chunk.get("citation_ref") or chunk.get("source_file") or "")
        if not ref:
            continue
        doc = docs.setdefault(
            ref,
            {
                "citation_ref": ref,
                "source": chunk.get("source", ""),
                "source_file": public_citation_ref(chunk.get("source_file") or ref),
                "source_title": chunk.get("source_title", ""),
                "file_summary": chunk.get("file_summary", ""),
                "chunk_count": 0,
                "best_chunk_id": "",
                "best_chunk_score": 0.0,
                "score": 0.0,
                "match_reasons": set(),
            },
        )
        doc["chunk_count"] += 1
        chunk_score, reasons = score_chunk(index, chunk, query, query_counts)
        if chunk_score > doc["best_chunk_score"]:
            doc["best_chunk_score"] = chunk_score
            doc["best_chunk_id"] = chunk.get("chunk_id", "")
        doc["score"] = max(float(doc["score"]), chunk_score)
        doc["match_reasons"].update(reasons)

    candidates = []
    for doc in docs.values():
        doc["score"] = round(float(doc["score"]), 6)
        doc["best_chunk_score"] = round(float(doc["best_chunk_score"]), 6)
        doc["match_reasons"] = sorted(doc["match_reasons"])
        if doc["score"] > 0:
            candidates.append(doc)
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:top_k]
