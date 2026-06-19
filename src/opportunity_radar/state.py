from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
import urllib.error
import urllib.request

from .models import now_iso


MAX_STORED_RUNS = 50


class JsonStore(Protocol):
    def load(self) -> dict[str, Any]:
        ...

    def save(self, payload: dict[str, Any]) -> None:
        ...


def empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": now_iso(),
        "seen_jobs": {},
        "sent_jobs": {},
        "sent_weeks": {},
        "evaluated_jobs": {},
        "source_cache": {},
        "runs": [],
    }


class FileJsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_state()
        return json.loads(self.path.read_text(encoding="utf-8-sig"))

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = now_iso()
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class GithubJsonStore:
    def __init__(self, repo: str, path: str, token: str, ref: str = "main", *, user_agent: str) -> None:
        self.repo = repo
        self.path = path.strip("/")
        self.token = token
        self.ref = ref
        self.user_agent = user_agent

    def _request(self, url: str, *, method: str = "GET", data: bytes | None = None) -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=data,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method=method,
        )

    def _url(self) -> str:
        return f"https://api.github.com/repos/{self.repo}/contents/{quote(self.path)}?ref={quote(self.ref)}"

    def load_with_sha(self) -> tuple[dict[str, Any], str]:
        try:
            with urllib.request.urlopen(self._request(self._url()), timeout=30) as response:
                item = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return empty_state(), ""
            raise
        content = base64.b64decode(str(item.get("content", "")).encode("utf-8")).decode("utf-8-sig")
        return json.loads(content), str(item.get("sha", ""))

    def load(self) -> dict[str, Any]:
        payload, _sha = self.load_with_sha()
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        write_payload = payload
        for attempt in range(3):
            current, sha = self.load_with_sha()
            if attempt:
                write_payload = merge_state(current, write_payload)
            write_payload["updated_at"] = now_iso()
            body: dict[str, Any] = {
                "message": "Update OpportunityRadar state",
                "content": base64.b64encode(json.dumps(write_payload, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii"),
                "branch": self.ref,
            }
            if sha:
                body["sha"] = sha
            put_url = f"https://api.github.com/repos/{self.repo}/contents/{quote(self.path)}"
            try:
                with urllib.request.urlopen(
                    self._request(put_url, method="PUT", data=json.dumps(body).encode("utf-8")),
                    timeout=30,
                ):
                    return
            except urllib.error.HTTPError as exc:
                if exc.code == 409 and attempt < 2:
                    continue
                raise


def merge_state(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = empty_state()
    merged["seen_jobs"] = {**current.get("seen_jobs", {}), **incoming.get("seen_jobs", {})}
    merged["sent_jobs"] = {**current.get("sent_jobs", {}), **incoming.get("sent_jobs", {})}
    merged["sent_weeks"] = {**current.get("sent_weeks", {}), **incoming.get("sent_weeks", {})}
    merged["evaluated_jobs"] = {**current.get("evaluated_jobs", {}), **incoming.get("evaluated_jobs", {})}
    merged["source_cache"] = {**current.get("source_cache", {}), **incoming.get("source_cache", {})}
    runs = list(current.get("runs", [])) + list(incoming.get("runs", []))
    seen_run_ids = set()
    unique_runs = []
    for run in runs:
        run_id = str(run.get("run_id", ""))
        if run_id and run_id in seen_run_ids:
            continue
        if run_id:
            seen_run_ids.add(run_id)
        unique_runs.append(run)
    merged["runs"] = unique_runs[-MAX_STORED_RUNS:]
    merged["updated_at"] = now_iso()
    return merged


def state_store_from_env(root: Path) -> JsonStore:
    repo = os.environ.get("GITHUB_STATE_REPO", "").strip()
    token = os.environ.get("GITHUB_STATE_TOKEN", "").strip()
    if repo and token:
        return GithubJsonStore(
            repo,
            os.environ.get("GITHUB_STATE_PATH", "opportunity-state.json"),
            token,
            os.environ.get("GITHUB_STATE_REF", "main"),
            user_agent="opportunity-radar-state",
        )
    path = Path(os.environ.get("OPPORTUNITY_STATE_PATH", "data/state/opportunity-state.local.json"))
    if not path.is_absolute():
        path = root / path
    return FileJsonStore(path)


def load_json_from_github(repo: str, path: str, token: str, ref: str = "main") -> dict[str, Any]:
    encoded_path = quote(path.strip("/"))
    encoded_ref = quote(ref)
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw",
            "Authorization": f"Bearer {token}",
            "User-Agent": "opportunity-radar-config",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
