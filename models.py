import uuid
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class FetchOperation(Base):
    __tablename__ = "fetch_operations"
    id = Column(Integer, primary_key=True)
    tracking_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    repo_name = Column(String, unique=True, index=True)  # Make repo_name unique
    created_at = Column(DateTime)
    updated_at = Column(DateTime)  # Add updated_at field
    issues = relationship("Issue", back_populates="fetch_operation", cascade="all, delete-orphan")

class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, unique=True, index=True)
    title = Column(String)
    body = Column(Text)
    state = Column(String)
    labels = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    url = Column(String)
    repo_name = Column(String)
    fetch_operation_id = Column(Integer, ForeignKey("fetch_operations.id"))
    fetch_operation = relationship("FetchOperation", back_populates="issues")
