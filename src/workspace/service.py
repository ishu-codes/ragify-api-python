import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio.session import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from fastapi import HTTPException, UploadFile
from langchain_core.messages import AIMessage, HumanMessage, messages_from_dict

from src.utils.files import ensure_dir, remove_dir

from ..config.db import async_session_maker
from ..ragify_client import (
    GrobidIngestor,
    builder,
    ingest_document,
    vector_store_manager,
)
from .repository import SessionRepository, UploadRepository, WorkspaceRepository
from .utils import replace_extension

_magika = None


def _get_magika():
    global _magika
    if _magika is None:
        from magika import Magika

        _magika = Magika()
    return _magika


def _invalid_userId():
    raise HTTPException(status_code=400, detail="Invalid userId")


def _normalize_workspace_updates(name: str, description: str, tags: list[str]) -> dict:
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Workspace name is required")

    return {
        "name": normalized_name,
        "description": description.strip(),
        "tags": [tag.strip() for tag in tags if tag.strip()],
    }


def _workspace_upload_dir(workspace_id: int) -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "storage"
        / "workspaces"
        / str(workspace_id)
    )


def _upload_log(status_id: int, message: str):
    print(f"[upload:{status_id}] {message}")


async def _append_upload_log(db: AsyncSession, status_id: int, message: str):
    status = await UploadRepository.get_upload_status_by_id(db, status_id)
    if status is None:
        return

    logs = [
        *status.logs,
        {"message": message, "created_at": datetime.now(UTC).isoformat()},
    ]
    await UploadRepository.update_upload_status(status, {"logs": logs})
    _upload_log(status_id, message)


async def _set_file_status(
    db: AsyncSession,
    status_id: int,
    file_id: str,
    next_status: str,
    error: str | None = None,
):
    status = await UploadRepository.get_upload_status_by_id(db, status_id)
    if status is None:
        return

    next_files = []
    for file in status.files:
        if file["id"] == file_id:
            next_files.append({**file, "status": next_status, "error": error})
        else:
            next_files.append(file)

    await UploadRepository.update_upload_status(status, {"files": next_files})


async def _ensure_workspace_access(db: AsyncSession, workspace_id: int, user_id: int):
    workspace = await WorkspaceRepository.get_workspace_by_id(db, workspace_id)

    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace could not be found")

    if workspace.user_id != user_id:
        raise HTTPException(status_code=403, detail="Workspace access denied")

    return workspace


def _group_files_by_type(files: list[dict]) -> dict[str, list[dict]]:
    files_by_type: dict[str, list[dict]] = {}
    for file in files:
        files_by_type.setdefault(file["kind"], []).append(file)
    return files_by_type


def _read_file_bytes(storage_path: str) -> bytes:
    content = Path(storage_path).read_bytes()
    if not content:
        raise ValueError("File is empty")
    return content


async def _process_pdf_files(
    db: AsyncSession,
    status_id: int,
    workspace_id: int,
    upload_dir: str,
    files: list[dict],
) -> tuple[int, int]:
    try:
        ingestor = GrobidIngestor(str(workspace_id), upload_dir)
        ingestor.ingest()

        # PDFs processed successfully - update all PDF file statuses
        for file in files:
            await _set_file_status(db, status_id, file["id"], "completed")
            await _append_upload_log(
                db, status_id, f"Successfully processed PDF: {file['name']}"
            )
        return len(files), 0

    except Exception as exc:
        # Grobid processing failed - mark all PDFs as failed
        error_msg = str(exc)
        for file in files:
            await _set_file_status(db, status_id, file["id"], "failed", error_msg)
            await _append_upload_log(
                db,
                status_id,
                f"Failed to process PDF {file['name']}: {error_msg}",
            )
        return 0, len(files)


async def _process_text_files(
    db: AsyncSession,
    status_id: int,
    workspace_id: int,
    files: list[dict],
    *,
    chunk_type: str,
    file_label: str,
) -> tuple[int, int]:
    successful_count = 0
    failed_count = 0

    for file in files:
        try:
            content = _read_file_bytes(file["storage_path"])
            chunks = await asyncio.to_thread(
                ingest_document,
                workspace_id,
                file["name"],
                file["kind"],
                content,
                chunk_type,
            )

            await _set_file_status(db, status_id, file["id"], "completed")
            await _append_upload_log(
                db,
                status_id,
                f"Successfully processed {file_label} file: {file['name']} ({len(chunks)} chunks)",
            )
            successful_count += 1

        except Exception as exc:
            await _set_file_status(db, status_id, file["id"], "failed", str(exc))
            await _append_upload_log(
                db,
                status_id,
                f"Failed to process {file_label} file {file['name']}: {exc}",
            )
            failed_count += 1

    return successful_count, failed_count


async def _finalize_upload_status(
    db: AsyncSession, status_id: int, successful_count: int, failed_count: int
):
    status = await UploadRepository.get_upload_status_by_id(db, status_id)
    if status is None:
        return

    if successful_count > 0:
        await UploadRepository.update_upload_status(
            status,
            {
                "status": "completed",
                "completed_at": datetime.now(UTC),
                "error": None,
            },
        )
        await _append_upload_log(
            db,
            status_id,
            f"Upload completed: {successful_count} file(s) processed successfully, {failed_count} failed",
        )
    elif failed_count > 0:
        await UploadRepository.update_upload_status(
            status,
            {
                "status": "failed",
                "completed_at": datetime.now(UTC),
                "error": f"All files failed to process. {failed_count} file(s) failed.",
            },
        )
        await _append_upload_log(
            db,
            status_id,
            f"Upload failed: all {failed_count} file(s) failed to process",
        )
    else:
        await UploadRepository.update_upload_status(
            status,
            {
                "status": "failed",
                "completed_at": datetime.now(UTC),
                "error": "No files were processed",
            },
        )
        await _append_upload_log(
            db, status_id, "Upload failed: no files were processed"
        )


async def _process_uploaded_files(
    db: AsyncSession, status_id: int, workspace_id: int, upload_dir: str
):
    status = await UploadRepository.get_upload_status_by_id(db, status_id)
    if status is None:
        return

    await UploadRepository.update_upload_status(
        status, {"status": "processing", "error": None}
    )
    await _append_upload_log(db, status_id, "Starting background file processing")

    successful_count = 0
    failed_count = 0

    for file_type, files in _group_files_by_type(status.files).items():
        await _append_upload_log(
            db, status_id, f"Processing {len(files)} {file_type} file(s)"
        )

        if file_type == "pdf":
            successful, failed = await _process_pdf_files(
                db, status_id, workspace_id, upload_dir, files
            )
        elif file_type == "md":
            successful, failed = await _process_text_files(
                db,
                status_id,
                workspace_id,
                files,
                chunk_type="markdown",
                file_label="markdown",
            )
        else:
            successful, failed = await _process_text_files(
                db,
                status_id,
                workspace_id,
                files,
                chunk_type=file_type or "file",
                file_label=file_type,
            )

        successful_count += successful
        failed_count += failed

    await _finalize_upload_status(db, status_id, successful_count, failed_count)
    await db.commit()


async def _run_upload_processing(status_id: int, workspace_id: int, upload_dir: str):
    """Process uploaded files in a background task with its own DB session."""
    async with async_session_maker() as db:
        await _process_uploaded_files(db, status_id, workspace_id, upload_dir)


# Workspace Service


class WorkspaceService:
    @staticmethod
    async def get_workspaces(db: AsyncSession, user_id: int):
        return await WorkspaceRepository.get_all_workspaces(db, user_id)
        # return serialize_workspaces(workspaces)

    @staticmethod
    async def get_workspace(db: AsyncSession, workspace_id: int, user_id: int):
        return await _ensure_workspace_access(db, workspace_id, user_id)
        # return serialize_workspace(workspace)

    @staticmethod
    async def create_workspace(db: AsyncSession, user_id: int):
        workspace = await WorkspaceRepository.create_new_workspace(db, user_id)
        await db.commit()
        await db.refresh(workspace)

        print(workspace)
        if workspace:
            await asyncio.to_thread(
                vector_store_manager.create_collection, str(workspace.id)
            )
        return workspace

    @staticmethod
    async def update_workspace_details(
        db: AsyncSession,
        workspace_id: int,
        user_id: int,
        name: str,
        description: str,
        tags: list[str],
    ):
        workspace = await _ensure_workspace_access(db, workspace_id, user_id)
        await WorkspaceRepository.update_workspace(
            workspace, updates=_normalize_workspace_updates(name, description, tags)
        )
        await db.commit()
        await db.refresh(workspace)
        return workspace

    @staticmethod
    async def delete_workspace(db: AsyncSession, workspace_id: int, user_id: int):
        await _ensure_workspace_access(db, workspace_id, user_id)
        await WorkspaceRepository.delete_workspace(db, workspace_id)
        await db.commit()

        upload_dir = _workspace_upload_dir(workspace_id)
        remove_dir(str(upload_dir))

        return {"id": workspace_id}


# Session Service


class SessionService:
    @staticmethod
    async def get_workspace_sessions(db: AsyncSession, workspace_id: int, user_id: int):
        await _ensure_workspace_access(db, workspace_id, user_id)
        return await SessionRepository.get_sessions_by_workspace_id(db, workspace_id)

    @staticmethod
    async def get_session_messages(
        db: AsyncSession, workspace_id: int, session_id: int, user_id: int
    ):
        await _ensure_workspace_access(db, workspace_id, user_id)

        session = await SessionRepository.get_session_by_id(db, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Session could not be found")
        return session

    @staticmethod
    async def query_rag(
        db: AsyncSession,
        workspace_id: int,
        session_id: int | None,
        query: str,
        user_id: int,
    ):
        await _ensure_workspace_access(db, workspace_id, user_id)

        if not session_id:
            session = await SessionRepository.create_session(db, workspace_id)
        else:
            session = await SessionRepository.get_session_by_id(db, session_id)

        if session is None:
            raise HTTPException(status_code=404, detail="Session could not be found")

        chat_messages = messages_from_dict(session.messages)
        chat_messages.append(HumanMessage(content=query))

        # The RAG graph (retrieval + evaluation + generation) is synchronous and
        # can take a while; run it in a worker thread so the event loop keeps
        # serving other requests, and bound it so the request can never hang.
        print("[query] Starting RAG graph invocation")
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    builder.invoke,
                    {"messages": chat_messages, "workspace_id": workspace_id},
                ),
                timeout=240,
            )
        except asyncio.TimeoutError:
            print("[query] RAG graph invocation timed out")
            raise HTTPException(
                status_code=504, detail="Query timed out. Please try again."
            ) from None
        print("[query] RAG graph invocation finished")
        output_text = result["messages"][-1].content
        chat_messages.append(AIMessage(content=output_text))

        await SessionRepository.update_messages(session, chat_messages)
        await db.commit()
        await db.refresh(session)
        return {
            "session_id": session.id,
            "session_name": session.name,
            "created_at": session.created_at.isoformat(),
            "answer": output_text,
        }

    @staticmethod
    async def rename_session(
        db: AsyncSession, workspace_id: int, session_id: int, user_id: int, name: str
    ):
        await _ensure_workspace_access(db, workspace_id, user_id)

        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(status_code=400, detail="Session name is required")

        session = await SessionRepository.get_session_by_id(db, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Session could not be found")

        await SessionRepository.update_session(session, {"name": normalized_name})
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    async def remove_session(
        db: AsyncSession, workspace_id: int, session_id: int, user_id: int
    ):
        await _ensure_workspace_access(db, workspace_id, user_id)

        session = await SessionRepository.get_session_by_id(db, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Session could not be found")

        await SessionRepository.delete_session(db, session_id)
        await db.commit()
        return {"id": session_id}

    @staticmethod
    async def remove_all_sessions(db: AsyncSession, workspace_id: int, user_id: int):
        await _ensure_workspace_access(db, workspace_id, user_id)
        await WorkspaceRepository.delete_workspace_sessions(db, workspace_id)
        await db.commit()
        return {"workspace_id": workspace_id}


# Upload Service


class UploadService:
    @staticmethod
    async def get_upload_status(
        db: AsyncSession, workspace_id: int, status_id: int, user_id: int
    ):
        await _ensure_workspace_access(db, workspace_id, user_id)
        status = await UploadRepository.get_upload_status_by_id(db, status_id)

        if (
            status is None
            or status.workspace_id != workspace_id
            or status.user_id != user_id
        ):
            raise HTTPException(
                status_code=404, detail="Upload status could not be found"
            )

        return status
        # return serialize_upload_status(status)

    @staticmethod
    async def determine_type_and_save_doc(file: UploadFile, upload_dir: Path):
        try:
            if not file.filename:
                return None

            file_id = str(uuid4())
            file_bytes = await file.read()

            magika_result = _get_magika().identify_bytes(file_bytes)
            mime_type = (
                magika_result.output.mime_type
                if magika_result.ok
                else "application/octet-stream"
            )
            # file_extension = replace_extension(file.filename, mime_type)
            filename = replace_extension(file.filename, mime_type)

            target_path = upload_dir / f"{file_id}-{filename}"
            target_path.write_bytes(file_bytes)

            return {
                "id": file_id,
                "name": filename,
                "kind": Path(filename).suffix.lower().lstrip(".") or "file",
                "size": len(file_bytes),
                "mime_type": mime_type,
                "storage_path": str(target_path),
                "status": "uploaded",
                "error": None,
                "created_at": datetime.now(UTC).isoformat(),
            }
        except Exception as err:
            print(f"[upload] failed receiving {file.filename}: {err}")

    @staticmethod
    async def upload_docs(
        db: AsyncSession,
        workspace_id: int,
        user_id: int,
        files: list[UploadFile] | None,
    ):
        await _ensure_workspace_access(db, workspace_id, user_id)

        if not files:
            raise HTTPException(status_code=400, detail="No documents provided")

        upload_dir = _workspace_upload_dir(workspace_id)
        ensure_dir(str(upload_dir))

        # material_records = filter(
        #     lambda record: record is not None,
        #     run_in_threads(
        #         lambda file: await UploadService.determine_type_and_save_doc(
        #             file, upload_dir
        #         ),
        #         files
        #     )
        # )
        material_records = list(
            filter(
                None,
                await asyncio.gather(
                    *(
                        UploadService.determine_type_and_save_doc(f, upload_dir)
                        for f in files
                    )
                ),
            )
        )

        if not material_records:
            raise HTTPException(
                status_code=400, detail="No files were uploaded successfully"
            )

        status = await UploadRepository.create_upload_status(
            db, workspace_id, user_id, material_records
        )
        await db.commit()
        await db.refresh(status)
        await _append_upload_log(
            db, status.id, f"Received {len(material_records)} files from client"
        )
        asyncio.create_task(
            _run_upload_processing(status.id, workspace_id, str(upload_dir))
        )

        return {
            "status_id": status.id,
            "message": f"Uploaded {len(material_records)} files. Processing started.",
        }
