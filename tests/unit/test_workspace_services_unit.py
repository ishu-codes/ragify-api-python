"""Unit tests for workspace, session and upload service behavior."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, UploadFile

from src.workspace import service as workspace_service
from src.workspace.models import Session, Workspace
from src.workspace.repository import SessionRepository, UploadRepository, WorkspaceRepository


def _workspace(*, workspace_id: int = 11, user_id: int = 3) -> Workspace:
    workspace = Workspace(
        user_id=user_id,
        name="Java notes",
        description="Testing",
        tags=["java"],
        materials=[],
        storage_bytes=0,
    )
    workspace.id = workspace_id
    workspace.created_at = datetime.now(UTC)
    workspace.updated_at = workspace.created_at
    return workspace


def _session(*, session_id: int = 21, workspace_id: int = 11) -> Session:
    session = Session(
        workspace_id=workspace_id,
        name="Untitled Session",
        messages=[],
    )
    session.id = session_id
    session.created_at = datetime.now(UTC)
    session.updated_at = session.created_at
    return session


def test_normalize_workspace_updates_trims_and_drops_empty_tags():
    result = workspace_service._normalize_workspace_updates(
        "  Research  ",
        "  Notes  ",
        [" java ", "", " testing "],
    )

    assert result == {
        "name": "Research",
        "description": "Notes",
        "tags": ["java", "testing"],
    }


def test_normalize_workspace_updates_rejects_blank_names():
    with pytest.raises(HTTPException) as exc_info:
        workspace_service._normalize_workspace_updates("  ", "", [])

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Workspace name is required"


def test_group_files_by_type_preserves_file_order():
    groups = workspace_service._group_files_by_type(
        [
            {"id": "1", "kind": "pdf"},
            {"id": "2", "kind": "md"},
            {"id": "3", "kind": "pdf"},
        ]
    )

    assert [file["id"] for file in groups["pdf"]] == ["1", "3"]
    assert [file["id"] for file in groups["md"]] == ["2"]


async def test_workspace_access_returns_owned_workspace(monkeypatch):
    workspace = _workspace()
    monkeypatch.setattr(
        WorkspaceRepository,
        "get_workspace_by_id",
        AsyncMock(return_value=workspace),
    )

    result = await workspace_service._ensure_workspace_access(AsyncMock(), 11, 3)

    assert result is workspace


@pytest.mark.parametrize(
    ("workspace", "status_code", "detail"),
    [
        (None, 404, "Workspace could not be found"),
        (_workspace(user_id=99), 403, "Workspace access denied"),
    ],
)
async def test_workspace_access_rejects_missing_and_foreign_workspaces(
    monkeypatch, workspace, status_code, detail
):
    monkeypatch.setattr(
        WorkspaceRepository,
        "get_workspace_by_id",
        AsyncMock(return_value=workspace),
    )

    with pytest.raises(HTTPException) as exc_info:
        await workspace_service._ensure_workspace_access(AsyncMock(), 11, 3)

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail == detail


async def test_create_workspace_commits_and_creates_the_vector_collection(monkeypatch):
    db = AsyncMock()
    workspace = _workspace()
    ensure_cap = AsyncMock()
    create_workspace = AsyncMock(return_value=workspace)
    create_collection = Mock()
    monkeypatch.setattr(workspace_service, "ensure_workspace_cap", ensure_cap)
    monkeypatch.setattr(
        WorkspaceRepository,
        "create_new_workspace",
        create_workspace,
    )
    monkeypatch.setattr(
        workspace_service.vector_store_manager,
        "create_collection",
        create_collection,
    )

    result = await workspace_service.WorkspaceService.create_workspace(db, 3)

    assert result is workspace
    ensure_cap.assert_awaited_once_with(db, 3)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(workspace)
    create_collection.assert_called_once_with("11")


async def test_update_workspace_normalizes_values(monkeypatch):
    db = AsyncMock()
    workspace = _workspace()
    monkeypatch.setattr(
        workspace_service,
        "_ensure_workspace_access",
        AsyncMock(return_value=workspace),
    )

    result = await workspace_service.WorkspaceService.update_workspace_details(
        db,
        11,
        3,
        "  New name ",
        "  New description ",
        [" java ", ""],
    )

    assert result.name == "New name"
    assert result.description == "New description"
    assert result.tags == ["java"]
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(workspace)


async def test_query_stores_the_user_and_assistant_messages(monkeypatch):
    db = AsyncMock()
    workspace = _workspace()
    session = _session()
    monkeypatch.setattr(
        workspace_service,
        "_ensure_workspace_access",
        AsyncMock(return_value=workspace),
    )
    require_credit = AsyncMock()
    monkeypatch.setattr(workspace_service, "require_query_credit", require_credit)
    monkeypatch.setattr(
        SessionRepository,
        "create_session",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        workspace_service.builder,
        "invoke",
        lambda payload: {
            "messages": [{"role": "assistant", "content": "Mocked answer"}],
            "seen": payload,
        },
    )

    result = await workspace_service.SessionService.query_rag(
        db,
        workspace_id=11,
        session_id=None,
        query="What changed?",
        user_id=3,
    )

    assert result["session_id"] == 21
    assert result["answer"] == "Mocked answer"
    assert session.messages == [
        {"role": "user", "content": "What changed?"},
        {"role": "assistant", "content": "Mocked answer"},
    ]
    require_credit.assert_awaited_once_with(db, 3, 11)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(session)


async def test_query_rolls_back_when_the_rag_call_fails(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(
        workspace_service,
        "_ensure_workspace_access",
        AsyncMock(return_value=_workspace()),
    )
    monkeypatch.setattr(workspace_service, "require_query_credit", AsyncMock())
    monkeypatch.setattr(
        SessionRepository,
        "create_session",
        AsyncMock(return_value=_session()),
    )

    def fail(_):
        raise RuntimeError("RAG unavailable")

    monkeypatch.setattr(workspace_service.builder, "invoke", fail)

    with pytest.raises(RuntimeError, match="RAG unavailable"):
        await workspace_service.SessionService.query_rag(
            db,
            workspace_id=11,
            session_id=None,
            query="Question",
            user_id=3,
        )

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_rename_session_rejects_wrong_workspace(monkeypatch):
    monkeypatch.setattr(
        workspace_service,
        "_ensure_workspace_access",
        AsyncMock(return_value=_workspace()),
    )
    monkeypatch.setattr(
        SessionRepository,
        "get_session_by_id",
        AsyncMock(return_value=_session(workspace_id=99)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await workspace_service.SessionService.rename_session(
            AsyncMock(), 11, 21, 3, "New name"
        )

    assert exc_info.value.status_code == 404


async def test_determine_type_and_save_doc_writes_the_upload(tmp_path):
    upload = UploadFile(filename="notes.txt", file=BytesIO(b"important notes"))

    record = await workspace_service.UploadService.determine_type_and_save_doc(
        upload,
        tmp_path,
    )

    assert record["name"] == "notes.txt"
    assert record["kind"] == "txt"
    assert record["size"] == len(b"important notes")
    assert Path(record["storage_path"]).read_bytes() == b"important notes"


async def test_upload_docs_spends_credits_and_creates_the_status(monkeypatch, tmp_path):
    db = AsyncMock()
    workspace = _workspace()
    status = SimpleNamespace(id=55, files=[], logs=[])
    monkeypatch.setattr(
        workspace_service,
        "_ensure_workspace_access",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(
        workspace_service,
        "_workspace_upload_dir",
        lambda _: tmp_path,
    )
    monkeypatch.setattr(workspace_service, "ensure_storage_capacity", AsyncMock())
    spend = AsyncMock(return_value=True)
    monkeypatch.setattr(workspace_service, "spend_credits", spend)
    monkeypatch.setattr(workspace_service, "add_workspace_storage", AsyncMock())
    create_status = AsyncMock(return_value=status)
    monkeypatch.setattr(
        UploadRepository,
        "create_upload_status",
        create_status,
    )
    monkeypatch.setattr(
        workspace_service,
        "_append_upload_log",
        AsyncMock(),
    )

    def consume_task(coroutine):
        coroutine.close()
        return Mock()

    monkeypatch.setattr(workspace_service.asyncio, "create_task", consume_task)
    file = UploadFile(filename="notes.txt", file=BytesIO(b"notes"))

    result = await workspace_service.UploadService.upload_docs(
        db,
        workspace_id=11,
        user_id=3,
        files=[file],
    )

    assert result == {
        "status_id": 55,
        "message": "Uploaded 1 files. Processing started.",
    }
    spend.assert_awaited_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(status)


async def test_upload_processing_marks_markdown_as_completed(monkeypatch, tmp_path):
    document = tmp_path / "notes.md"
    document.write_text("# Notes", encoding="utf-8")
    status = SimpleNamespace(
        id=60,
        status="uploaded",
        error=None,
        completed_at=None,
        logs=[],
        files=[
            {
                "id": "file-1",
                "name": "notes.md",
                "kind": "md",
                "storage_path": str(document),
                "status": "uploaded",
                "error": None,
            }
        ],
    )
    db = AsyncMock()
    monkeypatch.setattr(
        UploadRepository,
        "get_upload_status_by_id",
        AsyncMock(return_value=status),
    )
    async def update_status(status, updates):
        for key, value in updates.items():
            setattr(status, key, value)

    monkeypatch.setattr(
        UploadRepository,
        "update_upload_status",
        update_status,
    )
    monkeypatch.setattr(workspace_service, "_append_upload_log", AsyncMock())
    ingest = Mock(return_value=2)
    monkeypatch.setattr(workspace_service, "ingest_document", ingest)

    await workspace_service._process_uploaded_files(db, 60, 11, str(tmp_path))

    assert status.status == "completed"
    assert status.error is None
    assert status.files[0]["status"] == "completed"
    ingest.assert_called_once_with(11, "notes.md", "md", b"# Notes", "markdown")
    db.commit.assert_awaited_once()
