from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# API request/response shapes. This keeps the main FastAPI file easier to scan.
class TelemetryPayload(BaseModel):
    identity: dict[str, Any] = Field(default_factory=dict)
    hardware: dict[str, Any] = Field(default_factory=dict)
    cpu: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    disk: dict[str, Any] = Field(default_factory=dict)
    network: dict[str, Any] = Field(default_factory=dict)
    packets: dict[str, Any] = Field(default_factory=dict)
    errors: dict[str, Any] = Field(default_factory=dict)
    alerts: list[str] = Field(default_factory=list)
    overall_status: str | None = None
    last_seen: str | None = None
    display_name: str | None = None
    tags: list[str] = Field(default_factory=list)


class TaskRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=120)
    mode: str = Field(default="safe", pattern="^(safe|ssh)$")


class TaskResult(BaseModel):
    task_id: str
    machine_key: str
    status: str
    output: str
    completed_at: str | None = None


class TerminalSessionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    machine_key: str | None = Field(default=None, max_length=160)


class TerminalCommandRequest(BaseModel):
    command: str = Field(default="", max_length=2000)


class TerminalSessionRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class MachineRegistration(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    host: str | None = Field(default=None, max_length=160)
    tags: list[str] = Field(default_factory=list)


class SshDeployRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    host: str = Field(..., min_length=1, max_length=160)
    controller_url: str | None = Field(default=None, max_length=300)
    login_type: str = Field(default="key", pattern="^(key|password)$")
    ssh_user: str = Field(default="pi", min_length=1, max_length=80)
    ssh_password: str | None = Field(default=None, max_length=500)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    tags: list[str] = Field(default_factory=list)


class MachineUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, max_length=160)
    tags: list[str] | None = None
