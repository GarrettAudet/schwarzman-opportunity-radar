from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote


DEFAULT_INDEX_REPO = "GarrettAudet/SchwarzmanQnA-Index"
DEFAULT_INDEX_PATH = "local-index.json"
DEFAULT_INDEX_BRANCH = "main"


def latest_timestamped_index(root: Path) -> Path | None:
    index_dir = root / "data" / "corpus" / "index"
    candidates = sorted(
        index_dir.glob("local-index-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def prepare_deploy_index(root: Path, explicit_index: str = "", refresh: bool = True) -> Path:
    deploy_index = root / "deploy" / "index" / "local-index.json"
    if explicit_index:
        source = Path(explicit_index).resolve()
    elif refresh:
        source = latest_timestamped_index(root) or deploy_index
    else:
        source = deploy_index

    if not source.exists():
        raise FileNotFoundError(f"Index file does not exist: {source}")

    deploy_index.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != deploy_index.resolve():
        shutil.copyfile(source, deploy_index)
        print(f"Copied {source} to {deploy_index}")
    return deploy_index


def github_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, object] | None = None,
    *,
    allow_404: bool = False,
) -> dict[str, object] | None:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "schwarzman-qna-index-uploader",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404 and allow_404:
            return None
        raise RuntimeError(f"GitHub API {method} failed with HTTP {exc.code}: {detail[:1000]}") from exc


def upload_index(
    *,
    index_path: Path,
    repo: str,
    repo_path: str,
    branch: str,
    token: str,
    message: str,
    dry_run: bool = False,
) -> None:
    if "/" not in repo:
        raise ValueError("repo must look like owner/name, for example GarrettAudet/SchwarzmanQnA-Index")

    content = index_path.read_bytes()
    encoded_content = base64.b64encode(content).decode("ascii")
    api_path = quote(repo_path.strip("/"), safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{api_path}"
    size_mb = len(content) / (1024 * 1024)
    if dry_run:
        print(f"Would upload {index_path} ({size_mb:.2f} MB) to {repo}:{repo_path} on {branch}.")
        print("Dry run only; no upload performed.")
        return

    current = github_json("GET", f"{url}?ref={quote(branch)}", token, allow_404=True)
    sha = None
    if current:
        current_type = str(current.get("type", ""))
        if current_type and current_type != "file":
            raise RuntimeError(f"GitHub path is not a file: {repo_path}")
        sha = str(current.get("sha") or "")

    payload: dict[str, object] = {
        "message": message,
        "content": encoded_content,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    action = "Update" if sha else "Create"
    print(f"{action} {repo}:{repo_path} from {index_path} ({size_mb:.2f} MB)")

    result = github_json("PUT", url, token, payload)
    commit = result.get("commit", {}) if result else {}
    commit_sha = str(commit.get("sha", ""))[:12]
    html_url = str(commit.get("html_url", ""))
    print(f"Uploaded index to {repo}:{repo_path} on {branch}.")
    if commit_sha:
        print(f"Commit: {commit_sha}")
    if html_url:
        print(html_url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload deploy/index/local-index.json to the private index repo.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--index", default="", help="Optional index JSON path. Defaults to the latest generated index.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_INDEX_REPO", DEFAULT_INDEX_REPO))
    parser.add_argument("--path", default=os.environ.get("GITHUB_INDEX_PATH", DEFAULT_INDEX_PATH))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_INDEX_REF", DEFAULT_INDEX_BRANCH))
    parser.add_argument("--message", default="Update local index")
    parser.add_argument(
        "--token-env",
        default="GITHUB_INDEX_UPLOAD_TOKEN",
        help="Environment variable containing a GitHub token with contents read/write access.",
    )
    parser.add_argument("--no-refresh", action="store_true", help="Upload the existing deploy/index/local-index.json.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare and validate inputs without uploading.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    token = os.environ.get(args.token_env, "").strip() or os.environ.get("GITHUB_INDEX_TOKEN", "").strip()
    if not token:
        if args.dry_run:
            token = "dry-run-token"
        else:
            print(
                f"Missing GitHub token. Set ${args.token_env} to a fine-grained token "
                "with Contents read/write access to the private index repo.",
                file=sys.stderr,
            )
            return 2

    index_path = prepare_deploy_index(root, args.index, refresh=not args.no_refresh)
    upload_index(
        index_path=index_path,
        repo=args.repo,
        repo_path=args.path,
        branch=args.branch,
        token=token,
        message=args.message,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
