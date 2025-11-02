from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class IssueBase(BaseModel):
    title: str
    body: Optional[str]
    state: str
    labels: Optional[str]
    created_at: datetime
    updated_at: datetime
    url: str
    repo_name: str

class IssueCreate(IssueBase):
    issue_id: int

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
    title: str
    body: str | None
    state: str
    labels: str | None
    created_at: str | None
    updated_at: str | None
    url: str
    repo_name: str

class IssuesResponse(BaseModel):
    message: str
    count: int
    issues: list[IssueOut]

class WebhookPayload(BaseModel):
    jsonrpc: str = "2.0"
    method: str = "new_issue_notification"
    params: IssueOut