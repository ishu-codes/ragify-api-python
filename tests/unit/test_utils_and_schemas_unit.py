"""Unit tests for small utilities, schemas and quota calculations."""

from datetime import UTC, datetime

import pytest

from src.config.settings import Config
from src.quotas import credits
from src.utils.colors import colorize
from src.utils.files import ensure_dir, remove_dir
from src.utils.json import load_json_file, save_to_json
from src.workspace.models import Session
from src.workspace.schemas import SessionMessagesResponse
from src.workspace.utils import mime_to_extension, replace_extension


def test_file_helpers_create_and_remove_a_directory(tmp_path):
    target = tmp_path / "nested" / "uploads"

    ensure_dir(str(target))
    (target / "a.txt").write_text("content", encoding="utf-8")
    remove_dir(str(target))

    assert not target.exists()


def test_json_helpers_round_trip_utf8_content(tmp_path):
    path = tmp_path / "data.json"
    payload = {"name": "Ragify", "description": "réseau"}

    save_to_json(str(path), payload)

    assert load_json_file(str(path)) == payload


def test_colorize_uses_default_reset_for_unknown_color():
    assert colorize("hello", "GREEN") == "\033[92mhello\033[0m"
    assert colorize("hello", "UNKNOWN") == "hello\033[0m"


def test_mime_helpers_map_known_and_unknown_types():
    assert mime_to_extension("application/pdf") == ".pdf"
    assert mime_to_extension("application/x-ragify") is None
    assert replace_extension("report", "application/pdf") == "report.pdf"
    assert replace_extension("notes.txt", "text/plain") == "notes.txt"


def test_session_messages_schema_normalizes_stored_messages():
    session = Session(
        workspace_id=4,
        name="History",
        messages=[
            {"role": "human", "content": "Question"},
            {"type": "ai", "data": {"content": "Answer"}},
            {"role": "assistant", "data": {"content": None}},
        ],
    )
    session.id = 8
    session.created_at = datetime.now(UTC)
    session.updated_at = session.created_at

    response = SessionMessagesResponse.model_validate(session)

    assert response.id == 8
    assert [message["role"] for message in response.messages] == [
        "user",
        "assistant",
        "assistant",
    ]
    assert [message["content"] for message in response.messages] == [
        "Question",
        "Answer",
        None,
    ]
    assert [message["id"] for message in response.messages] == [
        "msg-0",
        "msg-1",
        "msg-2",
    ]


def test_config_loads_a_prompt_from_the_packaged_yaml():
    config = Config()

    assert "{question}" in config.prompt("grading_prompt")


@pytest.mark.parametrize(
    ("total_bytes", "expected"),
    [
        (0, 1),
        (1, 1),
        (5 * 1024 * 1024, 1),
        (5 * 1024 * 1024 + 1, 2),
        (10 * 1024 * 1024, 2),
    ],
)
def test_upload_credit_cost_rounds_up_by_stride(monkeypatch, total_bytes, expected):
    monkeypatch.setattr(credits, "UPLOAD_CREDIT_STRIDE_BYTES", 5 * 1024 * 1024)

    assert credits.upload_credit_cost(total_bytes) == expected
