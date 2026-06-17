from __future__ import annotations

import re


CHUNK_FRAGMENT_RE = re.compile(r"#chunk=\d+$", re.I)
SOURCE_PREFIXES = (
    ("data/blackboard/", "blackboard/"),
    ("data/rencai/raw/", "rencai/"),
    ("data/rencai/", "rencai/"),
    ("data/transcripts/raw/", "transcripts/"),
    ("data/transcripts/", "transcripts/"),
    ("rencai/raw/", "rencai/"),
    ("transcripts/raw/", "transcripts/"),
)


def public_citation_ref(ref: object) -> str:
    text = str(ref or "").strip().replace("\\", "/")
    text = re.sub(r"^\./+", "", text)
    text = CHUNK_FRAGMENT_RE.sub("", text)
    lowered = text.lower()
    for old_prefix, new_prefix in SOURCE_PREFIXES:
        if lowered.startswith(old_prefix):
            return new_prefix + text[len(old_prefix) :]
    return text
