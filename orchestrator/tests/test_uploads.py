"""Uploads (F03, Blueprint Sections 11 and 14): caps, path traversal, allowlist, never executed."""

import io
import random
import stat
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.agent.helpers import analyze
from tests.conftest import UserFactory, bearer, login_as

BILLRITE = Path("/legacy/billrite")


def zip_of(files: dict[str, bytes], symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def billrite_zip() -> bytes:
    files = {f"src/{p.name}": p.read_bytes() for p in (BILLRITE / "src").glob("*.cbl")}
    files |= {f"copy/{p.name}": p.read_bytes() for p in (BILLRITE / "copy").glob("*.cpy")}
    return zip_of(files)


@pytest.fixture
def engineer(client: TestClient, make_user: UserFactory) -> dict[str, str]:
    return bearer(login_as(client, make_user("ENGINEER")))


@pytest.fixture
def uploads_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "demo_mode", False)


def upload(client: TestClient, headers: dict[str, str], data: bytes, filename: str = "sources.zip") -> Any:
    return client.post(
        "/api/v1/projects",
        data={"name": f"Upload {uuid.uuid4().hex[:8]}"},
        files={"archive": (filename, data, "application/zip")},
        headers=headers,
    )


def test_uploads_are_off_in_the_public_demo(client: TestClient, engineer: dict[str, str]) -> None:
    assert get_settings().demo_mode is True
    response = upload(client, engineer, billrite_zip())
    assert (response.status_code, response.json()["error"]["code"]) == (403, "UPLOADS_DISABLED")


def test_viewers_cannot_upload(client: TestClient, make_user: UserFactory, uploads_on: None) -> None:
    viewer = bearer(login_as(client, make_user("VIEWER")))
    assert upload(client, viewer, billrite_zip()).status_code == 403
    assert upload(client, {}, billrite_zip()).status_code == 401


def test_an_upload_becomes_a_project_that_can_be_analyzed_but_never_run(
    client: TestClient, engineer: dict[str, str], uploads_on: None
) -> None:
    response = upload(client, engineer, billrite_zip())
    assert response.status_code == 201, response.text
    project = response.json()
    assert (project["source_kind"], project["status"], project["source_file_count"]) == ("UPLOAD", "IMPORTED", 11)
    analyze(client, engineer, uuid.UUID(project["id"]))
    inventory = client.get(f"/api/v1/projects/{project['id']}/inventory", headers=engineer).json()
    assert inventory["summary"]["programs"] == 5


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ({"../evil.cbl": b"x"}, "UPLOAD_PATH_REJECTED"),
        ({"src/../../evil.cbl": b"x"}, "UPLOAD_PATH_REJECTED"),
        ({"/etc/evil.cbl": b"x"}, "UPLOAD_PATH_REJECTED"),
        ({"src\\evil.cbl": b"x"}, "UPLOAD_PATH_REJECTED"),
        ({"C:/evil.cbl": b"x"}, "UPLOAD_PATH_REJECTED"),
        ({"run.sh": b"id"}, "UPLOAD_TYPE_REJECTED"),
        ({"A.cbl": b"x", "B.exe": b"x"}, "UPLOAD_TYPE_REJECTED"),
        ({"A.cbl": "\u00e9".encode()}, "UPLOAD_NOT_TEXT"),
        ({"A.cbl": b"\x00\x01"}, "UPLOAD_NOT_TEXT"),
        ({"a/A.cbl": b"x", "b/A.cbl": b"y"}, "UPLOAD_DUPLICATE_NAME"),
        ({"RATES.cpy": b"x"}, "UPLOAD_NO_PROGRAMS"),
        ({}, "UPLOAD_EMPTY"),
    ],
)
def test_unsafe_archives_are_rejected(
    client: TestClient, engineer: dict[str, str], uploads_on: None, files: dict[str, bytes], code: str
) -> None:
    response = upload(client, engineer, zip_of(files))
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)


def test_a_symbolic_link_is_rejected(client: TestClient, engineer: dict[str, str], uploads_on: None) -> None:
    response = upload(client, engineer, zip_of({"A.cbl": b"x"}, symlink="link.cbl"))
    assert (response.status_code, response.json()["error"]["code"]) == (422, "UPLOAD_PATH_REJECTED")


def test_size_and_count_caps(
    client: TestClient, engineer: dict[str, str], uploads_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_max_files", 3)
    many = zip_of({f"P{i}.cbl": b"x" for i in range(4)})
    assert upload(client, engineer, many).json()["error"]["code"] == "UPLOAD_TOO_MANY_FILES"
    # A highly compressible member: tiny archive, large content. Stopped by the per-file cap.
    bomb = zip_of({"A.cbl": b" " * (settings.upload_max_file_bytes + 10)})
    assert len(bomb) < 10_000
    assert upload(client, engineer, bomb).json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    monkeypatch.setattr(settings, "upload_max_bytes", 2048)
    noise = random.Random(7)  # noqa: S311 - Test data, not a secret.
    big = zip_of({"A.cbl": bytes(noise.randrange(32, 127) for _ in range(9000))})
    assert len(big) > 2048
    assert upload(client, engineer, big).json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_only_zip_archives(client: TestClient, engineer: dict[str, str], uploads_on: None) -> None:
    assert upload(client, engineer, b"not a zip").json()["error"]["code"] == "UPLOAD_NOT_ZIP"
    response = upload(client, engineer, billrite_zip(), filename="sources.tar")
    assert response.json()["error"]["code"] == "UPLOAD_NOT_ZIP"
