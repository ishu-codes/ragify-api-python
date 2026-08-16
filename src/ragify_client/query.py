"""RAG query facade mirroring ``src.ragify.generation.builder`` over gRPC."""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    messages_from_dict,
)

from . import client as grpc
from .protos import ragify_pb2

_SERVICE = "rag"
DEFAULT_QUERY_TIMEOUT = 300.0


def _to_wire_message(message) -> ragify_pb2.ChatMessage:
    if isinstance(message, dict):
        if "role" in message and "content" in message:
            role = message["role"]
            if role in ("assistant", "ai"):
                message = AIMessage(content=message["content"])
            elif role == "system":
                message = SystemMessage(content=message["content"])
            else:
                message = HumanMessage(content=message["content"])
        else:
            message = messages_from_dict([message])[0]
    elif not isinstance(message, BaseMessage):
        message = HumanMessage(content=str(message))

    if isinstance(message, AIMessage):
        role = "assistant"
    elif isinstance(message, SystemMessage):
        role = "system"
    else:
        role = "user"

    return ragify_pb2.ChatMessage(role=role, content=message.content)


class _Builder:
    """Compatible with ``builder.invoke({...})`` from src.ragify.generation."""

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
        return {"messages": [AIMessage(content=response.answer)]}


builder = _Builder()
