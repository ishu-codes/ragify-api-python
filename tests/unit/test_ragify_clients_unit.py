"""Unit tests for the ragify-rag gRPC facades."""

from types import SimpleNamespace
from unittest.mock import Mock

import grpc
import pytest

from src.ragify_client import client as grpc_client
from src.ragify_client import query, vector_store
from src.ragify_client.ingestion import GrobidIngestor


def test_query_builder_maps_history_to_the_wire_contract(monkeypatch):
    captured = {}

    def fake_call(service, method, request, timeout):
        captured.update(
            service=service,
            method=method,
            request=request,
            timeout=timeout,
        )
        return SimpleNamespace(answer="A grounded answer")

    monkeypatch.setattr(query.grpc, "call", fake_call)

    result = query.builder.invoke(
        {
            "workspace_id": 42,
            "messages": [
                {"role": "human", "content": "Question"},
                {"type": "ai", "data": {"content": "Earlier answer"}},
                {"role": "tool", "content": "ignored role"},
            ],
        }
    )

    assert result == {
        "messages": [{"role": "assistant", "content": "A grounded answer"}]
    }
    assert captured["service"] == "rag"
    assert captured["method"] == "Query"
    assert captured["timeout"] == query.DEFAULT_QUERY_TIMEOUT
    assert captured["request"].workspace_id == 42
    assert [message.role for message in captured["request"].messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert [message.content for message in captured["request"].messages] == [
        "Question",
        "Earlier answer",
        "ignored role",
    ]


def test_vector_store_builds_a_create_collection_request(monkeypatch):
    captured = {}

    def fake_call(service, method, request, timeout):
        captured.update(service=service, method=method, request=request, timeout=timeout)

    monkeypatch.setattr(vector_store.grpc, "call", fake_call)

    vector_store.vector_store_manager.create_collection("17")

    assert captured["service"] == "vector_store"
    assert captured["method"] == "CreateCollection"
    assert captured["request"].workspace_id == 17
    assert captured["timeout"] == 60


def test_vector_store_rejects_non_numeric_collection_names():
    with pytest.raises(ValueError, match="must be a numeric workspace id"):
        vector_store.vector_store_manager.create_collection("notes")


def test_grobid_ingestor_is_a_noop_when_the_directory_has_no_pdfs(
    monkeypatch, tmp_path
):
    call = Mock()
    monkeypatch.setattr("src.ragify_client.ingestion.grpc.call", call)

    GrobidIngestor("11", str(tmp_path)).ingest()

    call.assert_not_called()


class _FakeRpcError(grpc.RpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code


def test_ragify_client_retries_once_after_unavailable(monkeypatch):
    client = grpc_client.RagifyClient("localhost:50051")
    stub = Mock()
    stub.Query.side_effect = [
        _FakeRpcError(grpc.StatusCode.UNAVAILABLE),
        "response",
    ]
    monkeypatch.setattr(
        client,
        "_connect",
        lambda: setattr(client, "_stubs", {"rag": stub}),
    )
    reset = Mock(wraps=client.reset)
    monkeypatch.setattr(client, "reset", reset)

    result = client.call("rag", "Query", object(), timeout=10)

    assert result == "response"
    assert stub.Query.call_count == 2
    reset.assert_called_once()


def test_ragify_client_converts_grpc_deadline_to_timeout(monkeypatch):
    client = grpc_client.RagifyClient("localhost:50051")
    stub = Mock()
    stub.Query.side_effect = _FakeRpcError(grpc.StatusCode.DEADLINE_EXCEEDED)
    monkeypatch.setattr(
        client,
        "_connect",
        lambda: setattr(client, "_stubs", {"rag": stub}),
    )

    with pytest.raises(TimeoutError, match="timed out after 3s"):
        client.call("rag", "Query", object(), timeout=3)
