from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import urllib.error
import urllib.request


DEFAULT_USER_AGENT = "OpportunityRadar/0.1 (+https://github.com/GarrettAudet/OpportunityRadar)"


@dataclass(frozen=True)
class FetchResponse:
    status: int
    url: str
    body: str
    headers: dict[str, str]


def fetch_url(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> FetchResponse:
    request_headers = {"User-Agent": DEFAULT_USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return FetchResponse(
                status=int(response.status),
                url=response.geturl(),
                body=body,
                headers={key.lower(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return FetchResponse(status=304, url=url, body="", headers={key.lower(): value for key, value in exc.headers.items()})
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} fetching {url}: {detail[:400]}") from exc


def conditional_headers(cache: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    etag = str(cache.get("etag", "")).strip()
    last_modified = str(cache.get("last_modified", "")).strip()
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers
