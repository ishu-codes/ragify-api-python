from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.utils import get_current_user_id, require_auth
from ..config.db import get_session
from .schemas import (
    IdResponse,
    QueryBody,
    QueryResponse,
    SessionMessagesResponse,
    SessionSummary,
    UpdateSessionBody,
    UpdateWorkspaceBody,
    UploadResponse,
    UploadStatusResponse,
    WorkspaceIdResponse,
    WorkspaceResponse,
)
from .service import SessionService, UploadService, WorkspaceService

router = APIRouter(dependencies=[Depends(require_auth)])


# Workspace


@router.get("/", response_model=list[WorkspaceResponse])
async def workspaces(
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await WorkspaceService.get_workspaces(db, user_id)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def workspace_detail(
    workspace_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await WorkspaceService.get_workspace(db, workspace_id, user_id)


@router.post("/", response_model=WorkspaceResponse, status_code=201)
async def new_workspace(
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await WorkspaceService.create_workspace(db, user_id)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: int,
    body: UpdateWorkspaceBody,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await WorkspaceService.update_workspace_details(
        db, workspace_id, user_id, body.name, body.description, body.tags
    )


@router.delete("/{workspace_id}", response_model=IdResponse)
async def delete_workspace_route(
    workspace_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await WorkspaceService.delete_workspace(db, workspace_id, user_id)


# Uploads


@router.post("/{workspace_id}/upload", response_model=UploadResponse)
async def workspace_upload(
    workspace_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await UploadService.upload_docs(db, workspace_id, user_id, files)


@router.get("/{workspace_id}/uploads/{status_id}", response_model=UploadStatusResponse)
async def workspace_upload_status(
    workspace_id: int,
    status_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await UploadService.get_upload_status(db, workspace_id, status_id, user_id)


# Sessions


@router.post("/{workspace_id}/query", response_model=QueryResponse)
async def workspace_query(
    workspace_id: int,
    body: QueryBody,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await SessionService.query_rag(
        db, workspace_id, body.session_id, body.query, user_id
    )


@router.get("/{workspace_id}/sessions", response_model=list[SessionSummary])
async def workspace_sessions(
    workspace_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await SessionService.get_workspace_sessions(db, workspace_id, user_id)


@router.get(
    "/{workspace_id}/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
)
async def workspace_session_messages(
    workspace_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await SessionService.get_session_messages(
        db, workspace_id, session_id, user_id
    )


@router.patch("/{workspace_id}/sessions/{session_id}", response_model=SessionSummary)
async def update_session_name(
    workspace_id: int,
    session_id: int,
    body: UpdateSessionBody,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await SessionService.rename_session(
        db, workspace_id, session_id, user_id, body.name
    )


@router.delete("/{workspace_id}/sessions/{session_id}", response_model=IdResponse)
async def delete_session_route(
    workspace_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await SessionService.remove_session(db, workspace_id, session_id, user_id)


@router.delete("/{workspace_id}/sessions", response_model=WorkspaceIdResponse)
async def delete_all_sessions_route(
    workspace_id: int,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    return await SessionService.remove_all_sessions(db, workspace_id, user_id)
