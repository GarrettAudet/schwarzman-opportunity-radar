# Backend and WhatsApp Plan

## Current Backend

The first backend is a free local HTTP service around the reviewed corpus agent.
It uses only Python standard library modules and the existing OpenRouter key.

Run it locally:

```powershell
python scripts\serve_backend.py --root . --host 127.0.0.1 --port 8765
```

Test it:

```powershell
python scripts\query_backend.py "What documents do I need for the X1 visa?"
```

Use retrieval-only mode for sub-second checks that do not spend model tokens:

```powershell
python scripts\query_backend.py --retrieval-only "How do I register WeChat?"
```

## Public Online Backend

For a real public URL, deploy from a private GitHub repo to Render.

This repo includes `render.yaml`, which creates a free Render web service:

```yaml
startCommand: python scripts/serve_backend.py --root . --host 0.0.0.0
healthCheckPath: /health
```

Render provides the `PORT` environment variable automatically. The backend
reads it at startup.

The deployable corpus index is generated locally at:

```text
deploy/index/local-index.json
```

That file contains reviewed corpus text and is ignored by Git. Do not commit it
or `.env`. Upload the index to private storage and set `SCHWARZMAN_INDEX_URL`
in Render's environment-variable settings. If the URL requires a bearer token,
set `SCHWARZMAN_INDEX_BEARER_TOKEN` as well.

After deployment, the online health URL will look like:

```text
https://<your-render-service>.onrender.com/health
```

Ask endpoint:

```text
https://<your-render-service>.onrender.com/ask
```

## API Contract

`GET /health`

Returns service status, loaded index path, and chunk count.

`POST /ask`

Request:

```json
{
  "question": "Can internships in China be paid?",
  "top_k": 6,
  "retrieval_only": false
}
```

Response:

```json
{
  "ok": true,
  "elapsed_ms": 12000,
  "response_type": "answer",
  "answer": "Answer:\n...\n\nEvidence:\n[1] ...",
  "retrieval": {
    "top_score": 42.1,
    "sources": []
  },
  "guardrail": {
    "blocked": false,
    "block_reason": "",
    "prompt_injection_score": 0.0
  }
}
```

## Free Hosting Path

The cheapest path is:

1. Run locally while testing quality and latency.
2. Put the same backend on a free or nearly-free small web service only when
   the WhatsApp webhook needs a public URL.
3. Keep the downloaded corpus private on that server and do not expose raw
   source files.
4. Add a group allowlist before connecting WhatsApp, so only the intended
   student group can use the bot.

## WhatsApp Caveats

WhatsApp is probably not fully free. WhatsApp Business Platform pricing is
per delivered message by market and message category. Meta describes service
messages inside the user support window as no charge, but pricing should be
checked again before launch:

https://business.whatsapp.com/products/platform-pricing

There is also a product-fit caveat. The official WhatsApp Business Platform is
designed for business messaging and customer support, not a general-purpose AI
assistant. This project should stay framed as a narrow student-resource support
bot over a reviewed corpus, not as a general AI chatbot.

Finally, official WhatsApp API integrations are usually best for 1:1 messages
between a user and a business number. Before building the webhook, verify
whether the chosen WhatsApp provider supports the exact group/community/channel
behavior needed. If not, the clean fallback is to run the bot as a 1:1 DM
assistant and post the number/link in the student group.

## WhatsApp Integration Shape

The WhatsApp adapter should be a thin webhook layer:

1. Receive WhatsApp message.
2. Verify the webhook signature and sender/group allowlist.
3. Normalize the message text.
4. Call `POST /ask`.
5. Send the returned `answer` back to WhatsApp.

The adapter should not know about retrieval, prompt construction, OpenRouter,
or corpus files. That keeps WhatsApp replaceable if the group later moves to
another chat app.
