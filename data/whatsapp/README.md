# WhatsApp Access Control

This folder is for local/staging access-control data.

The bot should store only the minimum WhatsApp identity needed for access
control:

- `wa_id`
- `phone_number`
- `profile_name`
- `status`
- timestamps and admin notes
- recent feedback and failed-question events for admin review

Local JSON files in this folder are ignored by git because they contain phone
numbers. For Render, prefer a durable store such as a private GitHub-backed JSON
file or a database; Render's free filesystem should not be the only source of
truth for enrolled users.

## Private Store Contract

For the hosted bot, set `GITHUB_ACCESS_REPO`, `GITHUB_ACCESS_PATH`,
`GITHUB_ACCESS_REF`, and `GITHUB_ACCESS_TOKEN`. The private GitHub JSON file is
then the authoritative access/audit store. The webhook checks it on every
incoming message before answering.

Recommended path:

```text
GITHUB_ACCESS_REPO=GarrettAudet/SchwarzmanQnA-Index
GITHUB_ACCESS_PATH=whatsapp-access.json
```

That private file stores:

- every WhatsApp user who has messaged the bot, including `wa_id`,
  `phone_number`, and WhatsApp display/profile name when provided
- user status: `pending`, `approved`, or `blocked`
- the ban list, represented by users with `status: blocked`
- feedback submitted with `/feedback ...`
- failed question events, including `not_found`, `out_of_scope`,
  `safety_refusal`, and agent/server failure response types
- lightweight retrieval metadata for failed questions, such as top score and
  top source, so you can see why the bot missed

The bot does not answer unless the private store, env allowlist, or local
development store marks the user approved. Blocked users are denied first.

Useful commands:

```powershell
python scripts\manage_whatsapp_access.py list --root .
python scripts\manage_whatsapp_access.py summary --root .
python scripts\manage_whatsapp_access.py blocked --root .
python scripts\manage_whatsapp_access.py feedback --root . --limit 25
python scripts\manage_whatsapp_access.py failures --root . --limit 25
python scripts\manage_whatsapp_access.py approve --root . --phone 15551234567 --name "Student Name"
python scripts\manage_whatsapp_access.py block --root . --phone 15551234567 --notes "Removed from group"
python scripts\manage_whatsapp_access.py revoke --root . --phone 15551234567
python scripts\manage_whatsapp_access.py remove --root . --phone 15551234567
```

Environment variables:

```text
WHATSAPP_PASSWORD=<password posted in the group, preferred user-facing name>
WHATSAPP_INVITE_CODE=<legacy env name; supported if WHATSAPP_PASSWORD is unset>
WHATSAPP_ALLOWED_NUMBERS=<optional comma-separated phone allowlist>
WHATSAPP_BLOCKED_NUMBERS=<optional comma-separated phone blocklist>
WHATSAPP_ALLOWED_WA_IDS=<optional comma-separated wa_id allowlist>
WHATSAPP_BLOCKED_WA_IDS=<optional comma-separated wa_id blocklist>
WHATSAPP_ACCESS_STORE_PATH=data/whatsapp/access-control.json
```

Optional private GitHub-backed storage:

```text
GITHUB_ACCESS_REPO=GarrettAudet/SchwarzmanQnA-Index
GITHUB_ACCESS_PATH=whatsapp-access.json
GITHUB_ACCESS_REF=main
GITHUB_ACCESS_TOKEN=<fine-grained token with contents read/write for the private repo>
```
