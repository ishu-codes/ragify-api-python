"""ragify_client — the backend's module-like interface to ragify-rag.

Importing this package looks like importing a normal library, but every call is
forwarded over gRPC to the ragify-rag server in ``src/ragify/grpc``.
"""

from . import client
from .ingestion import (
    GrobidIngestor,
    ingest_document,
    process_section,
    transcoder,
)
from .query import builder
from .vector_store import VectorStoreManager, vector_store_manager

__all__ = [
    "GrobidIngestor",
    "ingest_document",
    "process_section",
    "transcoder",
    "builder",
    "VectorStoreManager",
    "vector_store_manager",
    "client",
]
