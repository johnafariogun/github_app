from utils.data import fetch_issues_json
import os
import httpx
import json
import re



tools = [
    {"type": "function", "function": fetch_issues_json}
]


def handle_tool_calls(tool_calls):
    """Handle tool calls from OpenAI"""
    results = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        tool = globals().get(tool_name)
        result = tool(**arguments) if tool else {}

        results.append({
            "role": "tool",
            "content": json.dumps(result),
            "tool_call_id": tool_call.id
        })

    return results




def fetch_issues(owner: str, repo: str, state: str = "open", per_page: int = 30) -> dict:
    """
    Fetch issues for a GitHub repository using the public GitHub REST API.

    Args:
        owner: repo owner (user or org)
        repo: repo name
        state: issue state filter (open, closed, all)
        per_page: number of issues to return (max 100)

    Returns a dict with simplified issue information or an error key on failure.
    """
    try:
        if not owner or not repo:
            return {"error": "Both owner and repo must be provided."}

        url = f"https://api.github.com/repos/{owner}/{repo}/issues"
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"

        params = {"state": state, "per_page": per_page}
        resp = httpx.get(url, headers=headers, params=params, timeout=10.0)

        if resp.status_code != 200:
            return {"error": f"GitHub API returned {resp.status_code}: {resp.text}"}

        issues = resp.json()
        simplified = []
        for i in issues:
            # skip pull requests
            if isinstance(i, dict) and i.get("pull_request"):
                continue

            simplified.append({
                "id": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "created_at": i.get("created_at"),
                "updated_at": i.get("updated_at"),
                "comments": i.get("comments"),
                "labels": [lab.get("name") for lab in i.get("labels", [])],
                "user": i.get("user", {}).get("login"),
                "url": i.get("html_url"),
                "body": (i.get("body") or "")[:500]
            })

        return {"owner": owner, "repo": repo, "count": len(simplified), "issues": simplified}

    except Exception as e:
        return {"error": f"An unexpected error occurred: {str(e)}"}
