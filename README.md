# GitHub Issues Agent (A2A)

A small FastAPI-based agent that accepts A2A JSON-RPC style requests and returns GitHub issues for a repository. It is intentionally lightweight: the agent fetches issue data from the GitHub REST API and returns a TaskResult with a short textual summary plus an artifact that contains the issues payload.

## What this project contains
- `main.py` — FastAPI app with a lifespan that initializes the `GitHubIssuesAgent`. Exposes:
  - `GET /health` — simple health check
  - `POST /a2a/issues` — receives A2A JSON-RPC requests (see `models/a2a.py`) and forwards messages to the agent
- `agents/github_issues_agent.py` — the A2A agent that parses incoming messages, extracts an `owner/repo` string, calls `utils.fetch_issues`, and returns a `TaskResult` containing a textual summary and an artifact with the raw issues data.
- `models/a2a.py` — Pydantic models describing the A2A message envelope and JSON-RPC shaped requests/responses.
- `utils/utils.py` and `utils/data.py` — `fetch_issues` function (HTTP call to GitHub) and tool schema.


## Quick start (development)

1. Create and activate a virtual environment (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. 
```powershell
pip install -r requirements.txt
```

3. Optionally set a `GITHUB_TOKEN` in a `.env` file to increase API rate limits and access private repos.

4. Run the app:

```powershell
# from repository root
uvicorn main:app --reload --port 5001
```

## Request shape (A2A JSON-RPC)

The app expects JSON-RPC 2.0 requests at `/a2a/issues`. Two supported `method` values used by the Pydantic models are `message/send` and `execute`.

Minimal example to fetch issues for `octocat/Hello-World` (POST body):

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [ { "kind": "text", "text": "octocat/Hello-World" } ]
    },
    "configuration": {}
  }
}
```

The response follows `models/a2a.JSONRPCResponse` and contains a `TaskResult` in `result` with:
- `status` — task state and (optional) message
- `artifacts` — list of artifacts; the agent places the issues payload in an artifact named `issues_data` (with a `data` MessagePart containing owner, repo, count and issues list)

## How the agent extracts the repo

The agent attempts to extract `owner/repo` in this order:
1. From a `text` MessagePart (direct `owner/repo` string or a sentence containing it)
2. From a `data` MessagePart that is a dict with `owner` and `repo` keys
3. A fallback of taking the last two whitespace-separated tokens

If it cannot identify the repository, the agent returns a `TaskResult` with `state` set to `completed` and an explanatory message.
