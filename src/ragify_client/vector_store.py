"""Vector store facade mirroring the ragify-rag VectorStoreService."""

from __future__ import annotations

from . import client as grpc
from .protos import ragify_pb2

_SERVICE = "vector_store"


def _workspace_id(collection_name: str) -> int:
    try:
        return int(collection_name)
    except (TypeError, ValueError):
        raise ValueError(
            f"Collection name must be a numeric workspace id, got {collection_name!r}"
        ) from None


class VectorStoreManager:
    """Same call surface as the in-process manager, but backed by gRPC."""

    def create_collection(self, collection_name: str) -> None:
        grpc.call(
            _SERVICE,
            "CreateCollection",
            ragify_pb2.WorkspaceRequest(
                workspace_id=_workspace_id(collection_name)
            ),
            timeout=60,
        )

    def delete_collection(self, collection_name: str) -> bool:
        grpc.call(
            _SERVICE,
            "DeleteCollection",
            ragify_pb2.WorkspaceRequest(
                workspace_id=_workspace_id(collection_name)
            ),
            timeout=60,
        )
        return True

    def insert_documents(self, collection_name: str, documents: list) -> None:
        wire_documents = []
        for doc in documents:
            if isinstance(doc, dict):
                text = doc.get("page_content") or doc.get("text") or ""
                metadata = doc.get("metadata") or {}
            else:
                text = getattr(doc, "page_content", "") or ""
                metadata = getattr(doc, "metadata", None) or {}
            wire_documents.append(
                ragify_pb2.Document(
                    text=str(text),
                    metadata={
                        str(key): str(value) for key, value in metadata.items()
                    },
                )
            )
        grpc.call(
            _SERVICE,
            "InsertDocuments",
            ragify_pb2.InsertDocumentsRequest(
                workspace_id=_workspace_id(collection_name),
                documents=wire_documents,
            ),
            timeout=120,
        )


vector_store_manager = VectorStoreManager()
