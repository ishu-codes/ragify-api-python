"""Shared gRPC transport used by the ragify_client service facades.

The channel is created lazily on first use so the API can boot before the
ragify-rag server is reachable. Unavailable connections are retried once after
reconnecting, which keeps the facade resilient to ragify-rag restarts.
"""

from __future__ import annotations

import logging
import os
import threading

import grpc

from .protos import ragify_pb2_grpc

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "localhost:50051"
MAX_MESSAGE_LENGTH = 500 * 1024 * 1024


def endpoint() -> str:
    return os.getenv("RAGIFY_GRPC_ENDPOINT", DEFAULT_ENDPOINT)


def _tls_enabled() -> bool:
    return os.getenv("RAGIFY_GRPC_TLS", "").lower() in ("1", "true", "yes")


def _audience() -> str | None:
    """Audience Cloud Run checks on the ID token: the service's own URL.

    Derived from the endpoint so deployments do not have to set a second
    variable; ``RAGIFY_GRPC_AUDIENCE`` overrides it for custom domains.
    """
    explicit = os.getenv("RAGIFY_GRPC_AUDIENCE")
    if explicit:
        return explicit.rstrip("/")
    host = endpoint().rsplit(":", 1)[0]
    return f"https://{host}" if host else None


def _channel_credentials() -> grpc.ChannelCredentials:
    """TLS credentials carrying a Cloud Run ID token where one is available.

    ragify-rag runs with ``--no-allow-unauthenticated``, so every call must
    present a Google-signed ID token whose audience is the service URL. The
    token comes from the Cloud Run metadata server and is refreshed by
    ``AuthMetadataPlugin`` for the life of the channel. Off Google Cloud (local
    development, tests) there is no metadata server, so the channel falls back
    to plain TLS against endpoints that do not require authentication.
    """
    base = grpc.ssl_channel_credentials()
    audience = _audience()
    if not audience:
        return base

    try:
        from google.auth.transport import grpc as google_auth_grpc
        from google.auth.transport import requests as google_auth_requests
        from google.oauth2 import id_token

        request = google_auth_requests.Request()
        credentials = id_token.fetch_id_token_credentials(audience, request=request)
    except Exception as exc:  # no metadata server, or google-auth not installed
        logger.warning(
            "No ID token for %s (%s); calling ragify-rag unauthenticated",
            audience,
            exc,
        )
        return base

    plugin = google_auth_grpc.AuthMetadataPlugin(
        credentials=credentials, request=request
    )
    return grpc.composite_channel_credentials(
        base, grpc.metadata_call_credentials(plugin)
    )


class RagifyClient:
    """Lazy, reconnecting gRPC client for the ragify-rag services."""

    def __init__(self, endpoint_url: str | None = None):
        self._endpoint = endpoint_url or endpoint()
        self._lock = threading.Lock()
        self._channel: grpc.Channel | None = None
        self._stubs: dict[str, object] | None = None

    def _connect(self) -> None:
        channel_options = [
            ("grpc.max_send_message_length", MAX_MESSAGE_LENGTH),
            ("grpc.max_receive_message_length", MAX_MESSAGE_LENGTH),
        ]
        if _tls_enabled():
            # Cloud Run terminates TLS at its proxy; the client needs default
            # SSL credentials plus, once ragify-rag requires authentication, an
            # ID token for the service URL.
            channel = grpc.secure_channel(
                self._endpoint,
                _channel_credentials(),
                options=channel_options,
            )
        else:
            channel = grpc.insecure_channel(self._endpoint, options=channel_options)
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
