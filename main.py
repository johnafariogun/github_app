#!/usr/bin/env python3
"""
Single-file deployable GitHub Issues JSON-RPC service (MySQL backend)
- Single exposed endpoint: POST /
- Accepts repo identifiers in multiple formats:
    "/golang/go", "golang go", "golang/go", "https://github.com/golang/go", "golang,go"
- All calls are JSON-RPC 2.0 style in the request body (method + params)
- Uses SQLAlchemy with MySQL (expects DATABASE_URL env var, e.g. mysql+pymysql://user:pass@host:3306/dbname)
- Stores FetchOperation and Issue rows and replaces issues for a fetch operation atomically
- Provides methods: fetch_issues, get_issues, schedule_monitor
- Includes a webhook simulator mounted at /webhook-sim to receive webhook posts (for testing)
"""

import os
import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse
from datetime import datetime
import json
from fastapi.encoders import jsonable_encoder
import requests
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    BigInteger,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from dotenv import load_dotenv
# Load .env if present
load_dotenv()
# ---------------------------
# Configuration / Environment
# ---------------------------
DATABASE_URL = os.getenv("DATABASE_URL")  # e.g. mysql+pymysql://user:pass@host:3306/dbname
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required (e.g. mysql+pymysql://user:pass@host:3306/db)")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # optional but strongly recommended

PORT = int(os.getenv("PORT", "8000"))
PORT = 8080
# ---------------------------
# Database (SQLAlchemy)
# ---------------------------
# For MySQL we do not pass sqlite-specific connect_args
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ---------------------------
# Models
# ---------------------------
class FetchOperation(Base):
    __tablename__ = "fetch_operations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(String(64), unique=True, index=True, nullable=False, default=lambda: os.urandom(16).hex())
    repo_name = Column(String(255), unique=True, index=True, nullable=False)  # e.g. golang/go
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    issues = relationship("Issue", back_populates="fetch_operation", cascade="all, delete-orphan")

class Issue(Base):
    __tablename__ = "issues"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    issue_id = Column(BigInteger, unique=True, index=True, nullable=False)
    title = Column(String(1000), nullable=True)
    body = Column(Text, nullable=True)
    state = Column(String(50), nullable=True)
    labels = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    url = Column(String(1000), nullable=True)
    repo_name = Column(String(255), nullable=True)
    fetch_operation_id = Column(Integer, ForeignKey("fetch_operations.id"), nullable=True)
    fetch_operation = relationship("FetchOperation", back_populates="issues")

# Ensure tables exist
Base.metadata.create_all(bind=engine)

# ---------------------------
# Pydantic Schemas (responses/params)
# ---------------------------
class FetchOperationOut(BaseModel):
    tracking_id: str
    repo_name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class FetchResponse(BaseModel):
    message: str
    count: int
    fetch_op: FetchOperationOut

class IssueOut(BaseModel):
    id: int
    issue_id: int
    title: Optional[str] = None
    body: Optional[str] = None
    state: Optional[str] = None
    labels: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    url: Optional[str] = None
    repo_name: Optional[str] = None

class IssuesResponse(BaseModel):
    message: str
    count: int
    issues: List[IssueOut]

class WebhookPayload(BaseModel):
    jsonrpc: str = "2.0"
    method: str = "new_issue_notification"
    params: IssueOut

# ---------------------------
# Utility helpers
# ---------------------------
def get_db() -> Any:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def normalize_repo_identifier(raw: str) -> Tuple[str, str]:
    """
    Accept many formats and return (owner, repo)
    Supported inputs:
      - https://github.com/owner/repo
      - http://github.com/owner/repo
      - /owner/repo
      - owner/repo
      - owner repo
      - owner,repo
      - "ownerrepo" will error
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("Invalid repository identifier")

    s = raw.strip()
    # If it's a URL
    if s.startswith("http://") or s.startswith("https://"):
        u = urlparse(s)
        parts = u.path.strip("/").split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        raise ValueError("Invalid github URL format")

    # Remove leading slash
    if s.startswith("/"):
        s = s[1:]

    # Allow space, comma, or slash separators
    if " " in s:
        parts = [p for p in s.split(" ") if p]
    elif "," in s:
        parts = [p for p in s.split(",") if p]
    elif "/" in s:
        parts = [p for p in s.split("/") if p]
    else:
        # Attempt to split camel input like "ownerrepo" is ambiguous -> error
        raise ValueError("Repository identifier must be in formats: owner/repo, 'owner repo', or a GitHub URL")

    if len(parts) < 2:
        raise ValueError("Repository identifier must include owner and repo")
    return parts[0].strip(), parts[1].strip()

def parse_github_time(timestr: Optional[str]) -> Optional[datetime]:
    if not timestr:
        return None
    # GitHub uses ISO8601 with Z timezone: 2025-10-30T10:01:16Z
    try:
        return datetime.strptime(timestr, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        # Try fallback parsing
        try:
            return datetime.fromisoformat(timestr.replace("Z", "+00:00"))
        except Exception:
            return None

# ---------------------------
# CRUD operations
# ---------------------------
def get_or_create_fetch_operation(db: Session, repo_name: str) -> Tuple[FetchOperation, bool]:
    """
    Return (fetch_operation, created_flag)
    """
    fetch_op = db.query(FetchOperation).filter(FetchOperation.repo_name == repo_name).first()
    created = False
    now = datetime.utcnow()
    if fetch_op:
        fetch_op.updated_at = now
        db.add(fetch_op)
    else:
        fetch_op = FetchOperation(repo_name=repo_name, created_at=now, updated_at=now)
        db.add(fetch_op)
        created = True
    db.commit()
    db.refresh(fetch_op)
    return fetch_op, created

def replace_issues_for_fetch(db: Session, issues: List[Dict[str, Any]], fetch_operation: FetchOperation) -> Dict[str, Any]:
    """
    Delete existing issues for this fetch operation and bulk insert provided list.
    issues: list of dicts matching Issue fields (issue_id, title, body, state, labels, created_at (datetime), updated_at (datetime), url, repo_name)
    """
    try:
        # delete existing rows tied to this fetch_operation
        db.query(Issue).filter(Issue.fetch_operation_id == fetch_operation.id).delete(synchronize_session=False)
        db.flush()

        new_objs = []
        for itm in issues:
            itm_copy = dict(itm)
            itm_copy["fetch_operation_id"] = fetch_operation.id
            # ensure numeric types where appropriate
            if "issue_id" in itm_copy and itm_copy["issue_id"] is not None:
                try:
                    itm_copy["issue_id"] = int(itm_copy["issue_id"])
                except Exception:
                    pass
            new_objs.append(Issue(**itm_copy))

        if new_objs:
            db.bulk_save_objects(new_objs)

        db.commit()
        return {"tracking_id": fetch_operation.tracking_id, "total_issues": len(new_objs), "repo_name": fetch_operation.repo_name}
    except Exception as e:
        db.rollback()
        raise

def get_fetch_operation(db: Session, tracking_id: str) -> Optional[FetchOperation]:
    return db.query(FetchOperation).filter(FetchOperation.tracking_id == tracking_id).first()

def get_issues_by_tracking_id(db: Session, tracking_id: str, state: Optional[str] = None, label: Optional[str] = None) -> List[Issue]:
    q = db.query(Issue).join(FetchOperation, Issue.fetch_operation_id == FetchOperation.id).filter(FetchOperation.tracking_id == tracking_id)
    if state:
        q = q.filter(Issue.state == state)
    if label:
        q = q.filter(Issue.labels.like(f"%{label}%"))
    return q.all()

# ---------------------------
# RPC Handlers (business logic)
# ---------------------------
# In-memory monitors map -> (repo_full, webhook_url) -> thread
monitors: Dict[Tuple[str, str], threading.Thread] = {}

async def handle_fetch_issues_rpc(body: Dict[str, Any]) -> Dict[str, Any]:
    params = body.get("params", {}) or {}
    raw_repo = params.get("repo_url")
    if not raw_repo:
        return jsonrpc_error(body.get("id"), -32602, "Missing 'repo_url' parameter")

    try:
        owner, repo = normalize_repo_identifier(raw_repo)
    except Exception as e:
        return jsonrpc_error(body.get("id"), -32602, f"Invalid repo identifier: {e}")

    repo_full = f"{owner}/{repo}"
    db = next(get_db())
    try:
        fetch_op, created = get_or_create_fetch_operation(db, repo_full)
        # call GitHub API
        headers = {}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=all&per_page=100"
        resp = requests.get(url, headers=headers, timeout=15)
        try:
            resp.raise_for_status()
        except requests.HTTPError as he:
            # surface GitHub error code/message
            return jsonrpc_error(body.get("id"), -32002, f"GitHub API error: {resp.status_code} {resp.text}")

        data = resp.json()
        issues_to_insert = []
        for issue in data:
            if "pull_request" in issue:
                continue
            issues_to_insert.append({
                "issue_id": issue.get("id"),
                "title": issue.get("title"),
                "body": issue.get("body"),
                "state": issue.get("state"),
                "labels": ",".join([lbl.get("name") for lbl in issue.get("labels", [])]) if issue.get("labels") else None,
                "created_at": parse_github_time(issue.get("created_at")),
                "updated_at": parse_github_time(issue.get("updated_at")),
                "url": issue.get("html_url"),
                "repo_name": repo_full,
            })

        replace_issues_for_fetch(db, issues_to_insert, fetch_op)

        resp_model = FetchResponse(
            message="Issues fetched and stored successfully",
            count=len(issues_to_insert),
            fetch_op=FetchOperationOut(
                tracking_id=fetch_op.tracking_id,
                repo_name=fetch_op.repo_name,
                created_at=fetch_op.created_at,
                updated_at=fetch_op.updated_at,
            )
        )
        return jsonrpc_result(body.get("id"), resp_model.dict())
    except Exception as e:
        return jsonrpc_error(body.get("id"), -32000, f"Internal server error: {e}")
    finally:
        db.close()

async def handle_get_issues_rpc(body: Dict[str, Any]) -> Dict[str, Any]:
    params = body.get("params", {}) or {}
    tracking_id = params.get("tracking_id")
    if not tracking_id:
        return jsonrpc_error(body.get("id"), -32602, "Missing 'tracking_id' parameter")
    state = params.get("state")
    label = params.get("label")

    db = next(get_db())
    try:
        fetch_op = get_fetch_operation(db, tracking_id)
        if not fetch_op:
            return jsonrpc_error(body.get("id"), -32602, "Tracking ID not found")

        issues = get_issues_by_tracking_id(db, tracking_id, state, label)
        issues_out = []
        for i in issues:
            issues_out.append({
                "id": int(i.id),
                "issue_id": int(i.issue_id),
                "title": i.title,
                "body": i.body,
                "state": i.state,
                "labels": i.labels,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
                "url": i.url,
                "repo_name": i.repo_name,
            })
        resp = {"message": "Issues retrieved successfully", "count": len(issues_out), "issues": issues_out}
        return jsonrpc_result(body.get("id"), resp)
    except Exception as e:
        return jsonrpc_error(body.get("id"), -32000, f"Internal server error: {e}")
    finally:
        db.close()

async def handle_schedule_monitor_rpc(body: Dict[str, Any]) -> Dict[str, Any]:
    params = body.get("params", {}) or {}
    raw_repo = params.get("repo_url")
    webhook_url = params.get("webhook_url")
    poll_interval = int(params.get("poll_interval", 60))

    if not raw_repo or not webhook_url:
        return jsonrpc_error(body.get("id"), -32602, "Missing 'repo_url' or 'webhook_url' parameter")

    try:
        owner, repo = normalize_repo_identifier(raw_repo)
    except Exception as e:
        return jsonrpc_error(body.get("id"), -32602, f"Invalid repo identifier: {e}")

    repo_full = f"{owner}/{repo}"
    key = (repo_full, webhook_url)

    if key in monitors:
        return jsonrpc_result(body.get("id"), {"status": "already_monitoring", "repo": repo_full, "webhook": webhook_url})

    def monitor_loop():
        seen = set()
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        while True:
            try:
                url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=100"
                r = requests.get(url, headers=headers, timeout=15)
                r.raise_for_status()
                for issue in r.json():
                    if "pull_request" in issue:
                        continue
                    iid = issue.get("id")
                    if iid not in seen:
                        seen.add(iid)
                        payload = WebhookPayload(
                            params=IssueOut(
                                id=int(issue.get("number", 0)),
                                issue_id=int(iid) if iid else 0,
                                title=issue.get("title"),
                                body=issue.get("body"),
                                state=issue.get("state"),
                                labels=",".join([lbl.get("name") for lbl in issue.get("labels", [])]) if issue.get("labels") else None,
                                created_at=issue.get("created_at"),
                                updated_at=issue.get("updated_at"),
                                url=issue.get("html_url"),
                                repo_name=repo_full
                            )
                        )
                        try:
                            httpx.post(webhook_url, json=payload.model_dump(), timeout=10.0)
                        except Exception as ex:
                            # swallow webhook delivery errors and continue monitoring
                            print("Webhook delivery failed:", ex)
                time.sleep(poll_interval)
            except Exception as ex:
                print("Monitor loop error:", ex)
                time.sleep(poll_interval)

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    monitors[key] = t
    return jsonrpc_result(body.get("id"), {"status": "monitoring_started", "repo": repo_full, "webhook": webhook_url})

# ---------------------------
# JSON-RPC helpers
# ---------------------------
def jsonrpc_error(req_id: Optional[Any], code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}

def jsonrpc_result(req_id: Optional[Any], result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}

# ---------------------------
# Single exposed POST endpoint (routes JSON-RPC methods)
# ---------------------------
app = FastAPI(title="GitHub Issues RPC (single endpoint)")

# webhook simulator app
from fastapi import FastAPI as FastAPIApp
webhook_sim_app = FastAPIApp()

@webhook_sim_app.post("/webhook-sim")
async def webhook_simulator(request: Request):
    payload = await request.json()
    print("[WebhookSim] Received payload:", json.dumps(payload, indent=2))
    return {"status": "received", "payload": payload}

# mount the simulator to allow testing
app.mount("/webhook-sim", webhook_sim_app)

@app.post("/")
async def handle_rpc(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder(jsonrpc_error(None, -32700, "Parse error: invalid JSON"))
        )

    # Basic JSON-RPC validation
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder(jsonrpc_error(None, -32600, "Invalid Request"))
        )

    method = body.get("method")
    if not method:
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder(jsonrpc_error(body.get("id"), -32600, "Invalid Request: 'method' required"))
        )

    # Dispatch methods
    try:
        if method == "fetch_issues":
            result = await handle_fetch_issues_rpc(body)
        elif method == "get_issues":
            result = await handle_get_issues_rpc(body)
        elif method == "schedule_monitor":
            result = await handle_schedule_monitor_rpc(body)
        else:
            return JSONResponse(
                status_code=404,
                content=jsonable_encoder(jsonrpc_error(body.get("id"), -32601, f"Method not found: {method}"))
            )

        # ✅ Always wrap output through jsonable_encoder for datetime safety
        return JSONResponse(content=jsonable_encoder(result))

    except Exception as e:
        # ✅ Even errors get encoded safely
        return JSONResponse(
            content=jsonable_encoder(jsonrpc_error(body.get("id"), -32603, f"Internal error: {e}"))
        )

# ---------------------------
# Simple runner
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
