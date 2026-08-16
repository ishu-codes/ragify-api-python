"""Ingestion facades mirroring ``src.ragify.ingestion`` over gRPC."""

from __future__ import annotations

from pathlib import Path

from . import client as grpc
from .protos import ragify_pb2

_SERVICE = "ingestion"


def ingest_document(
    workspace_id: int,
    filename: str,
    kind: str,
    content: bytes,
    chunk_type: str | None = None,
) -> int:
    """Convert (if needed), chunk and index one document; returns chunk count."""
    response = grpc.call(
        _SERVICE,
        "ProcessDocument",
        ragify_pb2.ProcessDocumentRequest(
            workspace_id=int(workspace_id),
            filename=filename,
            kind=kind or "",
            content=content,
            chunk_type=chunk_type or "",
        ),
        timeout=300,
    )
    return response.chunks


def process_section(paragraphs: list[str]) -> list[str]:
    """Chunk paragraphs exactly like ``src.ragify.ingestion.chunk_processor``."""
    response = grpc.call(
        _SERVICE,
        "ProcessSection",
        ragify_pb2.ProcessSectionRequest(paragraphs=list(paragraphs)),
        timeout=60,
    )
    return list(response.chunks)


class _Transcoder:
    def convert_to_markdown(self, storage_path: str) -> str:
        path = Path(storage_path)
        response = grpc.call(
            _SERVICE,
            "ConvertToMarkdown",
            ragify_pb2.ConvertToMarkdownRequest(
                filename=path.name,
                content=path.read_bytes(),
            ),
            timeout=120,
        )
        return response.markdown


transcoder = _Transcoder()


class GrobidIngestor:
    """Client twin of ``src.ragify.ingestion.grobid_ingestion.GrobidIngestor``."""

    def __init__(
        self,
        collection_name: str,
        input_dir: str,
        output_dir: str | None = None,
    ) -> None:
        self._collection_name = int(collection_name)
        self._input_dir = Path(input_dir)

    def ingest(self) -> None:
        pdfs = sorted(self._input_dir.glob("*.pdf"))
        if not pdfs:
            return

        files = [
            ragify_pb2.PdfFile(name=pdf.name, content=pdf.read_bytes())
            for pdf in pdfs
        ]
        response = grpc.call(
            _SERVICE,
            "IngestPdf",
            ragify_pb2.IngestPdfRequest(
                workspace_id=self._collection_name,
                files=files,
            ),
            timeout=1800,
        )

        errors = [
            f"{result.name}: {result.error}"
            for result in response.results
            if not result.ok
        ]
        if errors:
            raise RuntimeError("PDF ingestion failed: " + "; ".join(errors))
