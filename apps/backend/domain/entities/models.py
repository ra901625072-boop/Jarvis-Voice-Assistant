from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from db.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)
    role = Column(String(20), default="user", nullable=False) # admin, user
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TaskModel(Base):
    __tablename__ = "tasks_history"
    
    id = Column(String(50), primary_key=True, index=True)
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default="queued", nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

class WorkflowModel(Base):
    __tablename__ = "workflows"
    
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    steps_json = Column(Text, nullable=False) # JSON encoded steps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), nullable=True)
    action = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False) # success, failed
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
