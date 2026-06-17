from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ANSWER_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_REVIEW_MODEL = "google/gemini-3.5-flash"
DEFAULT_APP_TITLE = "Schwarzman Scholar Resources QA"


def load_env(root: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without printing secrets."""
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def openrouter_api_key(root: Path) -> str:
    load_env(root)
    return os.environ.get("OPENROUTER_API_KEY", "")


def answer_model() -> str:
    return os.environ.get("OPENROUTER_ANSWER_MODEL", DEFAULT_ANSWER_MODEL)


def review_model() -> str:
    return os.environ.get("OPENROUTER_REVIEW_MODEL", DEFAULT_REVIEW_MODEL)
