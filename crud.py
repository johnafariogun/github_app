from typing import Optional, List, Dict, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from models import Issue, FetchOperation
from sqlalchemy import select
from schemas import IssueCreate

def get_or_create_fetch_operation(db: Session, repo_name: str) -> Tuple[FetchOperation, bool]:
    """Get existing fetch operation or create new one if it doesn't exist.
    
    Returns:
        Tuple[FetchOperation, bool]: (fetch_operation, created)
        where created is True if a new operation was created, False if existing was returned
    """
    # Try to get existing fetch operation
    fetch_op = db.query(FetchOperation).filter(
        FetchOperation.repo_name == repo_name
    ).first()
    
    created = False
    now = datetime.utcnow()
    
    if fetch_op:
        # Update the updated_at timestamp
        fetch_op.updated_at = now
        db.add(fetch_op)
    else:
        # Create new fetch operation
        fetch_op = FetchOperation(
            repo_name=repo_name,
            created_at=now,
            updated_at=now
        )
        db.add(fetch_op)
        created = True
    
    db.commit()
    db.refresh(fetch_op)
    return fetch_op, created

def create_issue(db: Session, issues: list[dict], fetch_operation: FetchOperation):
    """
    Efficiently insert or update multiple issues without duplicate errors.
    Links issues to the provided fetch operation.
    """
    try:
        # First, remove all existing issues for this fetch operation
        # This ensures we don't have stale issues in the database
        db.query(Issue).filter(
            Issue.fetch_operation_id == fetch_operation.id
        ).delete(synchronize_session=False)
        
        # Now add all current issues
        new_issues = []
        for issue in issues:
            try:
                # Add fetch operation ID to the issue data
                issue["fetch_operation_id"] = fetch_operation.id
                new_issues.append(Issue(**issue))
            except Exception as e:
                print(f"Error processing issue {issue['issue_id']}: {str(e)}")
                continue

        if new_issues:
            db.bulk_save_objects(new_issues)
        
        db.commit()
        return {
            "tracking_id": fetch_operation.tracking_id,
            "total_issues": len(new_issues),
            "repo_name": fetch_operation.repo_name,
        }
    except Exception as e:
        db.rollback()
        print(f"Error in create_issue: {str(e)}")
        raise

def get_issues_by_tracking_id(
    db: Session, 
    tracking_id: str,
    state: Optional[str] = None, 
    label: Optional[str] = None
):
    """Get issues by tracking ID with optional filters."""
    try:
        # Join with FetchOperation to get issues by tracking_id
        query = db.query(Issue).join(
            FetchOperation, 
            Issue.fetch_operation_id == FetchOperation.id
        ).filter(FetchOperation.tracking_id == tracking_id)
        
        if state:
            query = query.filter(Issue.state == state)
        if label:
            query = query.filter(Issue.labels.like(f"%{label}%"))
            
        return query.all()
    except Exception as e:
        print(f"Error in get_issues_by_tracking_id: {str(e)}")
        return []

def get_fetch_operation(db: Session, tracking_id: str) -> Optional[FetchOperation]:
    """Get fetch operation by tracking ID."""
    return db.query(FetchOperation).filter(
        FetchOperation.tracking_id == tracking_id
    ).first()
