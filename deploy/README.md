# Deployment

This folder contains files needed by an online host.

## Important

`deploy/index/local-index.json` contains reviewed text chunks from the student
resource corpus. It is ignored by Git and should not be pushed to GitHub.

Use GitHub for code and provide the index to Render through private storage or
a signed URL.

## Render Setup

1. Create a GitHub repo for this project.
2. Push this repo to GitHub.
3. In Render, create a new Blueprint or Web Service from the private repo.
4. Use `render.yaml` if creating from Blueprint.
5. Set `OPENROUTER_API_KEY` in Render's environment variables.
6. Upload `deploy/index/local-index.json` somewhere private and set
   `SCHWARZMAN_INDEX_URL` to a signed/private download URL.
7. Confirm `/health` returns `ok: true`.

Render notes:

- Free web services sleep after idle time and may take about a minute to wake.
- The service must bind to `0.0.0.0` and Render's `PORT` environment variable.
- The checked-in deploy index is read-only; rebuild it locally after corpus updates.
