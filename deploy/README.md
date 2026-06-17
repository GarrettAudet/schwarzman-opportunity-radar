# Deployment

This folder contains files needed by an online host.

## Important

`deploy/index/local-index.json` contains reviewed text chunks from the student
resource corpus. It is ignored by Git and should not be pushed to GitHub.

Use GitHub for code and provide the index to Render through a separate private
GitHub repo or another private storage URL.

## Render Setup

1. Create a GitHub repo for this project.
2. Push this repo to GitHub.
3. Create a second private repo named `SchwarzmanQnA-Index`.
4. Push only `deploy/index/local-index.json` to that repo as `local-index.json`.
5. Create a fine-grained GitHub token with read-only Contents access to
   `SchwarzmanQnA-Index`.
6. In Render, create a new Blueprint or Web Service from the code repo.
7. Use `render.yaml` if creating from Blueprint.
8. Set `OPENROUTER_API_KEY` and `GITHUB_INDEX_TOKEN` in Render's environment
   variables.
9. Confirm `/health` returns `ok: true`.

Render notes:

- Free web services sleep after idle time and may take about a minute to wake.
- The service must bind to `0.0.0.0` and Render's `PORT` environment variable.
- The checked-in deploy index is read-only; rebuild it locally after corpus updates.
