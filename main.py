# main.py
from fastapi_jsonrpc import API, Entrypoint
from fastapi import Depends, BackgroundTasks, FastAPI, Request
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import Base
from crud import (
    create_issue,
    get_or_create_fetch_operation,
    get_issues_by_tracking_id,
    get_fetch_operation,
)
from urllib.parse import urlparse
from datetime import datetime
import requests
import os
import time
import threading
import httpx
from schemas import FetchResponse, IssueOut, FetchOperationOut, IssuesResponse, WebhookPayload

Base.metadata.create_all(bind=engine)

app = API(title="GitHub Issue Tracker JSON-RPC", version="1.0")
router = Entrypoint("/rpc")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def parse_repo_url(repo_url: str):
    parts = urlparse(repo_url).path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repo URL")
    return parts[0], parts[1]


@router.method()
def fetch_issues(repo_url: str, db: Session = Depends(get_db)) -> FetchResponse:
    """Fetch issues from GitHub and store them in the DB"""
    owner, repo = parse_repo_url(repo_url)
    repo_full_name = f"{owner}/{repo}"

    fetch_op, _ = get_or_create_fetch_operation(db, repo_full_name)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=all"

    headers = {}
    if "GITHUB_TOKEN" in os.environ:
        headers["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    def parse_time(ts):
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") if ts else None

    issues_data = [
        {
            "issue_id": issue["id"],
            "title": issue["title"],
            "body": issue.get("body"),
            "state": issue["state"],
            "labels": ",".join([l["name"] for l in issue["labels"]]),
            "created_at": parse_time(issue["created_at"]),
            "updated_at": parse_time(issue["updated_at"]),
            "url": issue["html_url"],
            "repo_name": repo_full_name,
        }
        for issue in response.json()
        if "pull_request" not in issue
    ]

    create_issue(db, issues_data, fetch_op)

    return FetchResponse(
    message="Issues fetched and stored successfully",
    count=len(issues_data),
    fetch_op=FetchOperationOut.model_validate(fetch_op, from_attributes=True),
)


@router.method()
def get_issues(
    tracking_id: str,
    state: str | None = None,
    label: str | None = None,
    db: Session = Depends(get_db),
) -> IssuesResponse:
    """Return stored issues by tracking ID"""
    fetch_op = get_fetch_operation(db, tracking_id)
    if not fetch_op:
        raise ValueError("Invalid tracking ID")
    issues = get_issues_by_tracking_id(db, tracking_id, state, label)
    issues_out = [
        IssueOut(
            id=int(getattr(i, "id", 0)),
            issue_id=int(getattr(i, "issue_id", 0)),
            title=str(getattr(i, "title", "")),
            body=str(getattr(i, "body", "")) if getattr(i, "body", None) is not None else None,
            state=str(getattr(i, "state", "")),
            labels=str(getattr(i, "labels", "")) if getattr(i, "labels", None) is not None else None,
            created_at=i.created_at.isoformat() if getattr(i, "created_at", None) else None,
            updated_at=i.updated_at.isoformat() if getattr(i, "updated_at", None) else None,
            url=str(getattr(i, "url", "")),
            repo_name=str(getattr(i, "repo_name", "")),
        )
        for i in issues
    ]
    return IssuesResponse(
        message="Issues retrieved successfully",
        count=len(issues_out),
        issues=issues_out,
    )


monitoring_repos = {}

@router.method()
def schedule_monitor(
    repo_url: str,
    webhook_url: str,
    poll_interval: int = 60,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """Schedule background monitoring of a GitHub repo for new issues and send to webhook."""
    owner, repo = parse_repo_url(repo_url)
    repo_full_name = f"{owner}/{repo}"
    
    def monitor_task():
        last_seen_ids = set()
        while True:
            try:
                url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=open"
                headers = {}
                if "GITHUB_TOKEN" in os.environ:
                    headers["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                issues = response.json()
                for issue in issues:
                    if "pull_request" in issue:
                        continue
                    if issue["id"] not in last_seen_ids:
                        # New issue detected
                        payload = WebhookPayload(
                            params=IssueOut(
                                id=issue["id"],
                                issue_id=issue["id"],
                                title=issue["title"],
                                body=issue.get("body"),
                                state=issue["state"],
                                labels=",".join([l["name"] for l in issue["labels"]]),
                                created_at=issue["created_at"],
                                updated_at=issue["updated_at"],
                                url=issue["html_url"],
                                repo_name=repo_full_name,
                            )
                        )
                        try:
                            httpx.post(webhook_url, json=payload.model_dump())
                        except Exception as e:
                            print(f"Failed to send webhook: {e}")
                        last_seen_ids.add(issue["id"])
                time.sleep(poll_interval)
            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(poll_interval)

    # Only one monitor per repo+webhook
    key = (repo_full_name, webhook_url)
    if key not in monitoring_repos:
        thread = threading.Thread(target=monitor_task, daemon=True)
        thread.start()
        monitoring_repos[key] = thread
    return {"status": "monitoring_started", "repo": repo_full_name, "webhook": webhook_url}

# Add a webhook simulation endpoint for testing
webhook_sim_app = FastAPI()

@webhook_sim_app.post("/webhook-sim")
async def webhook_sim(request: Request):
    payload = await request.json()
    print("[WebhookSim] Received webhook payload:", payload)
    return {"status": "received", "payload": payload}

# Mount the webhook simulation endpoint alongside the JSON-RPC API
app.mount("/webhook-sim", webhook_sim_app)

app.bind_entrypoint(router)

