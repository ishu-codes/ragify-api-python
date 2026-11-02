"""End-to-end HTTP and PostgreSQL tests for the core API flows."""

import pytest

from src.workspace import service as workspace_service

pytestmark = pytest.mark.integration


def _register(client, email: str, name: str = "Ishu") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "password123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_root_and_authentication_errors_use_the_public_api_shape(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["name"] == "ragify"

    unauthenticated = client.get("/api/v1/workspaces/")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"] == "Not authenticated"

    registered = _register(client, "auth@example.com")
    assert registered["user"]["credit_balance"] == 50

    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Ishu",
            "email": "auth@example.com",
            "password": "password123",
        },
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "User already exists"

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": "wrong-password"},
    )
    assert wrong_password.status_code == 400
    assert wrong_password.json()["detail"] == "Invalid email or password"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": "password123"},
    )
    assert login.status_code == 200

    token = login.json()["access_token"]
    current_user = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert current_user.status_code == 200
    assert current_user.json()["email"] == "auth@example.com"


def test_workspace_lifecycle_uses_the_database_and_rag_boundary(
    client, monkeypatch
):
    collections = []
    monkeypatch.setattr(
        workspace_service.vector_store_manager,
        "create_collection",
        collections.append,
    )
    registered = _register(client, "workspace@example.com")
    headers = {"Authorization": f"Bearer {registered['access_token']}"}

    created = client.post("/api/v1/workspaces/", headers=headers)
    assert created.status_code == 201
    workspace = created.json()
    assert workspace["name"] == "Untitled Workspace"
    assert workspace["tags"] == []
    assert collections == [str(workspace["id"])]

    updated = client.patch(
        f"/api/v1/workspaces/{workspace['id']}",
        headers=headers,
        json={
            "name": "  Python research  ",
            "description": "  Pytest and PostgreSQL  ",
            "tags": ["python", " testing ", ""],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Python research"
    assert updated.json()["description"] == "Pytest and PostgreSQL"
    assert updated.json()["tags"] == ["python", "testing"]

    listed = client.get("/api/v1/workspaces/", headers=headers)
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Python research"]

    deleted = client.delete(
        f"/api/v1/workspaces/{workspace['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"id": workspace["id"]}
    assert client.get("/api/v1/workspaces/", headers=headers).json() == []


def test_query_persists_history_and_returns_it_from_the_sessions_api(
    client, monkeypatch
):
    monkeypatch.setattr(
        workspace_service.vector_store_manager,
        "create_collection",
        lambda _: None,
    )
    payload = {
        "messages": [
            {"role": "assistant", "content": "Mocked RAG answer."}
        ]
    }
    seen = []

    def invoke(request):
        seen.append(
            {
                "messages": list(request["messages"]),
                "workspace_id": request["workspace_id"],
            }
        )
        return payload

    monkeypatch.setattr(workspace_service.builder, "invoke", invoke)
    registered = _register(client, "query@example.com")
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    workspace = client.post("/api/v1/workspaces/", headers=headers).json()

    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/query",
        headers=headers,
        json={"query": "What does pytest do?"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["session_name"] == "Untitled Session"
    assert result["answer"] == "Mocked RAG answer."
    assert seen == [
        {
            "messages": [{"role": "user", "content": "What does pytest do?"}],
            "workspace_id": workspace["id"],
        }
    ]

    sessions = client.get(
        f"/api/v1/workspaces/{workspace['id']}/sessions",
        headers=headers,
    )
    assert sessions.status_code == 200
    assert sessions.json()[0]["message_count"] == 2

    messages = client.get(
        f"/api/v1/workspaces/{workspace['id']}/sessions/"
        f"{result['session_id']}/messages",
        headers=headers,
    )
    assert messages.status_code == 200
    assert [
        (message["role"], message["content"])
        for message in messages.json()["messages"]
    ] == [
        ("user", "What does pytest do?"),
        ("assistant", "Mocked RAG answer."),
    ]


def test_upload_creates_a_status_without_waiting_for_ingestion(
    client, monkeypatch
):
    async def skip_processing(*_):
        return None

    monkeypatch.setattr(
        workspace_service,
        "_run_upload_processing",
        skip_processing,
    )
    monkeypatch.setattr(
        workspace_service.vector_store_manager,
        "create_collection",
        lambda _: None,
    )
    registered = _register(client, "upload@example.com")
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    workspace = client.post("/api/v1/workspaces/", headers=headers).json()

    upload = client.post(
        f"/api/v1/workspaces/{workspace['id']}/upload",
        headers=headers,
        files=[("files", ("notes.txt", b"important notes", "text/plain"))],
    )
    assert upload.status_code == 200, upload.text
    status_id = upload.json()["status_id"]

    status = client.get(
        f"/api/v1/workspaces/{workspace['id']}/uploads/{status_id}",
        headers=headers,
    )
    assert status.status_code == 200
    assert status.json()["status"] == "uploaded"
    assert status.json()["files"][0]["name"] == "notes.txt"
    assert status.json()["files"][0]["size"] == len(b"important notes")


def test_users_cannot_read_each_others_workspaces(client, monkeypatch):
    monkeypatch.setattr(
        workspace_service.vector_store_manager,
        "create_collection",
        lambda _: None,
    )
    owner = _register(client, "owner@example.com")
    other = _register(client, "other@example.com")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    workspace = client.post("/api/v1/workspaces/", headers=owner_headers).json()
    response = client.get(
        f"/api/v1/workspaces/{workspace['id']}",
        headers=other_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Workspace access denied"
