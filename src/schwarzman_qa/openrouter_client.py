from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import DEFAULT_APP_TITLE


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, api_key: str, app_title: str = DEFAULT_APP_TITLE) -> None:
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set")
        self.api_key = api_key
        self.app_title = app_title

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1200,
        response_format: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-OpenRouter-Title": self.app_title,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {body_text[:500]}") from exc
        except Exception as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

        try:
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise OpenRouterError(f"Unexpected OpenRouter response: {payload}") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(text[start : end + 1])
        else:
            raise
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
    raise ValueError("OpenRouter response did not contain a JSON object")
