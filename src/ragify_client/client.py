"""Shared gRPC transport used by the ragify_client service facades.

The channel is created lazily on first use so the API can boot before the
ragify-rag server is reachable. Unavailable connections are retried once after
reconnecting, which keeps the facade resilient to ragify-rag restarts.
"""

from __future__ import annotations

import os
import threading

import grpc

from .protos import ragify_pb2_grpc

DEFAULT_ENDPOINT = "localhost:50051"


def endpoint() -> str:
    return os.getenv("RAGIFY_GRPC_ENDPOINT", DEFAULT_ENDPOINT)


class RagifyClient:
    """Lazy, reconnecting gRPC client for the ragify-rag services."""

    def __init__(self, endpoint_url: str | None = None):
        self._endpoint = endpoint_url or endpoint()
        self._lock = threading.Lock()
        self._channel: grpc.Channel | None = None
        self._stubs: dict[str, object] | None = None

    def _connect(self) -> None:
        channel = grpc.insecure_channel(self._endpoint)
        self._channel = channel
        self._stubs = {
            "vector_store": ragify_pb2_grpc.VectorStoreServiceStub(channel),
            "ingestion": ragify_pb2_grpc.IngestionServiceStub(channel),
            "rag": ragify_pb2_grpc.RagServiceStub(channel),
        }

    def _stub(self, service: str):
        with self._lock:
            if self._stubs is None:
                self._connect()
            return self._stubs[service]

    def call(self, service: str, method: str, request, timeout: float):
        try:
            return getattr(self._stub(service), method)(request, timeout=timeout)
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise TimeoutError(
                    f"ragify-rag {service}.{method} timed out after {timeout}s"
                ) from exc
            if exc.code() == grpc.StatusCode.UNAVAILABLE:
                self.reset()
                return getattr(self._stub(service), method)(request, timeout=timeout)
            raise

    def reset(self) -> None:
        with self._lock:
            if self._channel is not None:
                self._channel.close()
            self._channel = None
            self._stubs = None

    def close(self) -> None:
        self.reset()


client = RagifyClient()


def call(service: str, method: str, request, timeout: float):
    return client.call(service, method, request, timeout)


def reset() -> None:
    client.reset()


def close() -> None:
    client.close()
