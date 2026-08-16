from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class WorkspaceInfo(BaseModel):
    id: int
    user_id: int
    name: str
    description: str
    tags: list[str]
    materials: list
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Workspace
class WorkspaceRequest(BaseModel):
    user_id: str


class WorkspaceResponse(WorkspaceInfo):
    model_config = ConfigDict(from_attributes=True)


class QueryBody(BaseModel):
    session_id: int | None = None
    query: str


class QueryResponse(BaseModel):
    session_id: int
    session_name: str
    created_at: str
    answer: str


class IdResponse(BaseModel):
    id: int


class WorkspaceIdResponse(BaseModel):
    workspace_id: int


class UploadResponse(BaseModel):
    status_id: int
    message: str


class UploadStatusResponse(BaseModel):
    id: int
    workspace_id: int
    user_id: int
    status: str
    files: list[dict]
    logs: list[dict]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    error: str | None

    model_config = ConfigDict(from_attributes=True)


class UpdateWorkspaceBody(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []


# Session
class UpdateSessionBody(BaseModel):
    name: str


class SessionSummary(BaseModel):
    id: int
    workspace_id: int
    name: str
    message_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionMessagesResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    created_at: datetime
    messages: list[dict]

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _serialize_messages(cls, data):
        if isinstance(data, dict):
            return data

        return {
            "id": data.id,
            "workspace_id": data.workspace_id,
            "name": data.name,
            "created_at": data.created_at,
            "messages": [
                {
                    "id": f"msg-{index}",
                    "role": "assistant" if message.get("type") == "ai" else "user",
                    "content": message.get("data", {}).get("content", ""),
                    "createdAt": message.get("data", {})
                    .get("additional_kwargs", {})
                    .get("created_at", ""),
                }
                for index, message in enumerate(data.messages)
            ],
        }
