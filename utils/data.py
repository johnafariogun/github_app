
fetch_issues_json = {
    "name": "fetch_issues",
    "description": "Fetch issues for a GitHub repository given owner and repo. Returns a list of issues with basic metadata.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner (user or organization)"},
            "repo": {"type": "string", "description": "Repository name"},
            "state": {"type": "string", "description": "Issue state: open, closed, or all", "default": "open"},
            "per_page": {"type": "integer", "description": "Number of issues to return (max 100)", "default": 30}
        },
        "required": ["owner", "repo"]
    }
}
# Schema for GitHub issues tool