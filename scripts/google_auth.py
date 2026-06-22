from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opportunity_radar.google_workspace import configured_google_scopes, google_token_uri, post_form  # noqa: E402


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    server_version = "OpportunityRadarOAuth/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [""])[0]  # type: ignore[attr-defined]
        self.server.auth_error = params.get("error", [""])[0]  # type: ignore[attr-defined]
        self.server.auth_state = params.get("state", [""])[0]  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if self.server.auth_code:  # type: ignore[attr-defined]
            self.wfile.write(b"OpportunityRadar authorization complete. You can close this tab.")
        else:
            self.wfile.write(b"OpportunityRadar authorization failed. Return to the terminal for details.")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def exchange_code_for_token(*, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, object]:
    try:
        return post_form(
            google_token_uri(),
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            user_agent="opportunity-radar-google-auth",
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google token exchange failed: HTTP {exc.code}: {detail[:500]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the one-time Google OAuth flow for Gmail sending and optional Google Sheets recipients.")
    parser.add_argument("--client-id", default=os.environ.get("GOOGLE_CLIENT_ID", ""), help="Google OAuth desktop/web client ID")
    parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_CLIENT_SECRET", ""), help="Google OAuth client secret")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GOOGLE_AUTH_PORT", "8766")), help="Local callback port")
    parser.add_argument("--scope", default=os.environ.get("GOOGLE_OAUTH_SCOPES", ""), help="Space-separated OAuth scopes")
    parser.add_argument("--no-browser", action="store_true", help="Print the auth URL without opening the browser")
    parser.add_argument("--json", action="store_true", help="Print token response as JSON")
    args = parser.parse_args()

    client_id = args.client_id.strip()
    client_secret = args.client_secret.strip()
    if not client_id or not client_secret:
        print("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required from your Google Cloud OAuth client.", file=sys.stderr)
        return 2

    scopes = args.scope.split() if args.scope.strip() else configured_google_scopes(include_sheets=True)
    state = secrets.token_urlsafe(18)
    redirect_uri = f"http://127.0.0.1:{args.port}/oauth2callback"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )

    server = HTTPServer(("127.0.0.1", args.port), OAuthCallbackHandler)
    server.auth_code = ""  # type: ignore[attr-defined]
    server.auth_error = ""  # type: ignore[attr-defined]
    server.auth_state = ""  # type: ignore[attr-defined]

    print("Open this URL and sign in as schwarzmanjobupdates:")
    print(auth_url)
    print()
    if not args.no_browser:
        webbrowser.open(auth_url)
    print("Waiting for Google OAuth callback...")
    server.handle_request()

    if server.auth_error:  # type: ignore[attr-defined]
        print(f"Google authorization failed: {server.auth_error}", file=sys.stderr)  # type: ignore[attr-defined]
        return 1
    if server.auth_state != state:  # type: ignore[attr-defined]
        print("Google authorization failed: state mismatch", file=sys.stderr)
        return 1
    code = str(server.auth_code)  # type: ignore[attr-defined]
    if not code:
        print("Google authorization failed: no code returned", file=sys.stderr)
        return 1

    token = exchange_code_for_token(client_id=client_id, client_secret=client_secret, code=code, redirect_uri=redirect_uri)
    if args.json:
        print(json.dumps(token, indent=2))
        return 0

    print()
    print("Add these to GitHub repository secrets:")
    print()
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    if token.get("refresh_token"):
        print(f"GOOGLE_REFRESH_TOKEN={token['refresh_token']}")
    else:
        print("GOOGLE_REFRESH_TOKEN was not returned. Re-run with --json, revoke the app grant, or use prompt=consent again.", file=sys.stderr)
        return 1
    print()
    print("Set repository variables:")
    print("OPPORTUNITY_SEND_PROVIDER=gmail_email")
    print("GOOGLE_GMAIL_FROM=Schwarzman Job Updates <schwarzmanjobupdates@gmail.com>")
    print("GOOGLE_RECIPIENTS_SHEET_ID=<your Google Sheet ID>")
    print("GOOGLE_RECIPIENTS_RANGE=Recipients!A:C")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
