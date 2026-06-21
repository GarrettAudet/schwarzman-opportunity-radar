from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opportunity_radar.microsoft_graph import configured_scope, poll_device_code, request_device_code  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the one-time Microsoft device-code flow and print the refresh token "
            "needed for Microsoft Graph email sending."
        )
    )
    parser.add_argument("--client-id", default=os.environ.get("MICROSOFT_CLIENT_ID", ""), help="Microsoft Entra application client ID")
    parser.add_argument("--tenant", default=os.environ.get("MICROSOFT_TENANT_ID", "common"), help="Tenant ID, domain, common, organizations, or consumers")
    parser.add_argument("--login-base-url", default=os.environ.get("MICROSOFT_LOGIN_BASE_URL", "https://login.microsoftonline.com"))
    parser.add_argument("--graph-base-url", default=os.environ.get("MICROSOFT_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0"))
    parser.add_argument("--scope", default=os.environ.get("MICROSOFT_SCOPE", ""), help="Override OAuth scopes")
    parser.add_argument("--json", action="store_true", help="Print token response as JSON")
    args = parser.parse_args()

    client_id = args.client_id.strip()
    if not client_id:
        print("MICROSOFT_CLIENT_ID is required. Create a Microsoft Entra app registration first.", file=sys.stderr)
        return 2

    scope = args.scope.strip() or configured_scope(args.graph_base_url)
    device = request_device_code(
        client_id=client_id,
        tenant=args.tenant,
        scope=scope,
        login_base=args.login_base_url,
        graph_base=args.graph_base_url,
    )
    message = str(device.get("message", "")).strip()
    if message:
        print(message)
    else:
        verification_uri = device.get("verification_uri") or device.get("verification_url")
        print(f"Open {verification_uri} and enter code {device.get('user_code')}")
    print()
    print("Waiting for Microsoft login and 2FA approval...")

    token = poll_device_code(
        client_id=client_id,
        device_code=str(device["device_code"]),
        tenant=args.tenant,
        interval=int(device.get("interval", 5) or 5),
        expires_in=int(device.get("expires_in", 900) or 900),
        login_base=args.login_base_url,
    )
    if args.json:
        print(json.dumps(token, indent=2))
        return 0

    print()
    print("Add these to GitHub repository secrets/variables:")
    print()
    print(f"MICROSOFT_CLIENT_ID={client_id}")
    print(f"MICROSOFT_TENANT_ID={args.tenant}")
    print(f"MICROSOFT_REFRESH_TOKEN={token['refresh_token']}")
    print()
    print("Set repository variable OPPORTUNITY_SEND_PROVIDER=microsoft_graph_email.")
    print("Set OPPORTUNITY_RECIPIENTS to the destination email address or Google Group.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
