"""
api/schemas.py — Typed Pydantic request and response schemas for JARVIS API.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=256, description="API Key or secret token")


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"


class UploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255, description="Name of the file to upload")
    content: str = Field(..., min_length=1, description="Base64-encoded binary file content")


class UploadResponse(BaseModel):
    status: str = "success"
    filepath: str
    file_id: str
    filename: str


class TaskCreateRequest(BaseModel):
    input: str = Field(..., min_length=1, description="Task command or natural language instruction")
    priority: Optional[str] = Field("normal", description="Task priority (normal, high, low)")
    session_id: Optional[str] = Field(None, description="Optional session tracking ID")


class WorkflowStepModel(BaseModel):
    name: Optional[str] = None
    agent: str = Field(..., description="Target specialist agent ID")
    action: str = Field(..., description="Action/task type to invoke")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Step arguments dictionary")


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Workflow display name")
    steps: List[WorkflowStepModel] = Field(..., min_length=1, description="Ordered workflow execution steps")
    description: Optional[str] = None


class ScheduleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Schedule name")
    cron: str = Field(..., min_length=5, max_length=64, description="Standard 5-field cron expression")
    workflow_id: str = Field(..., min_length=1, description="Target workflow ID to execute")
