"""RAG query facade mirroring the ragify-rag RagService over gRPC."""

from __future__ import annotations

from . import client as grpc
from .protos import ragify_pb2

_SERVICE = "rag"
DEFAULT_QUERY_TIMEOUT = 300.0

_WIRE_ROLES = {"user", "assistant", "system"}
_ROLE_ALIASES = {"human": "user", "ai": "assistant"}


def _to_wire_message(message) -> ragify_pb2.ChatMessage:
    if isinstance(message, dict):
        role = message.get("role") or message.get("type") or "user"
        content = message.get("content")
        if content is None and isinstance(message.get("data"), dict):
            content = message["data"].get("content")
    else:
        role, content = "user", str(message)

    role = _ROLE_ALIASES.get(role, role)
    if role not in _WIRE_ROLES:
        role = "user"
    return ragify_pb2.ChatMessage(role=role, content=str(content or ""))


class _Builder:
    """Compatible with ``builder.invoke({...})`` from the RAG graph."""

    def invoke(self, payload: dict, timeout: float = DEFAULT_QUERY_TIMEOUT) -> dict:
        workspace_id = int(payload["workspace_id"])
        messages = [_to_wire_message(message) for message in payload["messages"]]

        response = grpc.call(
            _SERVICE,
            "Query",
            ragify_pb2.QueryRequest(
                workspace_id=workspace_id,
                messages=messages,
            ),
            timeout=timeout,
        )
        return {"messages": [{"role": "assistant", "content": response.answer}]}


builder = _Builder()
