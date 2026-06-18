from __future__ import annotations

import re


CHUNK_FRAGMENT_RE = re.compile(r"#chunk=\d+$", re.I)
COMMON_FILE_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".txt",
    ".md",
    ".vtt",
    ".srt",
    ".csv",
    ".rtf",
)
SOURCE_PREFIXES = (
    ("data/blackboard/", "blackboard/"),
    ("data/rencai/raw/", "rencai/"),
    ("data/rencai/", "rencai/"),
    ("data/transcripts/raw/", "transcripts/"),
    ("data/transcripts/", "transcripts/"),
    ("rencai/raw/", "rencai/"),
    ("transcripts/raw/", "transcripts/"),
)


def collapse_duplicate_extension(text: str) -> str:
    """Clean accidental names like guide.pdf.pdf for public display."""
    cleaned = text
    lowered = cleaned.lower()
    for extension in COMMON_FILE_EXTENSIONS:
        doubled = extension + extension
        while lowered.endswith(doubled):
            cleaned = cleaned[: -len(extension)]
            lowered = cleaned.lower()
    return cleaned


def public_citation_ref(ref: object) -> str:
    text = str(ref or "").strip().replace("\\", "/")
    text = re.sub(r"^\./+", "", text)
    text = CHUNK_FRAGMENT_RE.sub("", text)
    lowered = text.lower()
    for old_prefix, new_prefix in SOURCE_PREFIXES:
        if lowered.startswith(old_prefix):
            return collapse_duplicate_extension(new_prefix + text[len(old_prefix) :])
    return collapse_duplicate_extension(text)


def public_source_title(title: object, fallback_ref: object = "") -> str:
    text = str(title or "").strip().replace("\\", "/")
    if not text:
        text = str(fallback_ref or "").strip().replace("\\", "/")
    text = CHUNK_FRAGMENT_RE.sub("", text)
    text = text.rsplit("/", 1)[-1]
    return collapse_duplicate_extension(text)
