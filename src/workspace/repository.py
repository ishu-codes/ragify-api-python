from datetime import UTC, datetime

from langchain_core.messages import BaseMessage
from langchain_core.messages.base import message_to_dict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio.session import AsyncSession

from .models import Session, UploadStatus, Workspace


def _apply_updates(model, updates: dict):
    for key, value in updates.items():
        if hasattr(model, key):
            setattr(model, key, value)


# ----- Workspace -----
class WorkspaceRepository:
    @staticmethod
    async def get_workspace_by_id(db: AsyncSession, workspace_id: int):
        return await db.get(Workspace, workspace_id)

    @staticmethod
    async def get_all_workspaces(db: AsyncSession, user_id: int):
        result = await db.execute(
            select(Workspace)
            .where(Workspace.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_new_workspace(db: AsyncSession, user_id: int):
        workspace = Workspace(
            user_id=user_id,
            name="Untitled Workspace",
            description="",
            tags=[],
            materials=[],
        )
        db.add(workspace)
        return workspace

    @staticmethod
    async def update_workspace(workspace: Workspace, updates: dict):
        _apply_updates(workspace, updates)

    @staticmethod
    async def append_workspace_materials(workspace: Workspace, materials: list[dict]):
        workspace.materials = [*workspace.materials, *materials]

    @staticmethod
    async def delete_workspace(db: AsyncSession, workspace_id: int):
        return await db.execute(delete(Workspace).where(Workspace.id == workspace_id))

    @staticmethod
    async def delete_workspace_sessions(db: AsyncSession, workspace_id: int):
        return await db.execute(
            delete(Session).where(Session.workspace_id == workspace_id)
        )


# ----- Session -----


class SessionRepository:
    @staticmethod
    async def get_session_by_id(db: AsyncSession, session_id: int):
        return await db.get(Session, session_id)

    @staticmethod
    async def get_sessions_by_workspace_id(db: AsyncSession, workspace_id: int):
        result = await db.execute(
            select(Session)
            .where(Session.workspace_id == workspace_id)
            .order_by(Session.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_session(db: AsyncSession, workspace_id: int):
        chat_session = Session(workspace_id=workspace_id, name="Untitled Session", messages=[])
        db.add(chat_session)
        return chat_session

    @staticmethod
    async def update_session(chat_session: Session, updates: dict):
        _apply_updates(chat_session, updates)

    @staticmethod
    async def delete_session(db: AsyncSession, session_id: int):
        return await db.execute(
            delete(Session).where(Session.id == session_id)
        )

    @staticmethod
    async def update_messages(chat_session: Session, messages: list[BaseMessage]):
        chat_session.messages = [message_to_dict(message) for message in messages]


# ----- Uploads -----


class UploadRepository:
    @staticmethod
    async def get_upload_status_by_id(db: AsyncSession, status_id: int):
        return await db.get(UploadStatus, status_id)

    @staticmethod
    async def create_upload_status(db: AsyncSession, workspace_id: int, user_id: int, files: list[dict]):
        now = datetime.now(UTC)
        upload_status = UploadStatus(
            workspace_id=workspace_id,
            user_id=user_id,
            status="uploaded",
            files=files,
            logs=[],
            created_at=now,
            updated_at=now,
            completed_at=None,
            error=None,
        )
        db.add(upload_status)
        return upload_status

    @staticmethod
    async def update_upload_status(upload_status: UploadStatus, updates: dict):
        _apply_updates(upload_status, updates)
