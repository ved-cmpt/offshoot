"""Project creation from an uploaded .zip of COBOL sources (F03, Blueprint Section 11).

The archive is read in memory and never extracted to disk. Rejected, each with a 422 and a
fixed code: anything that is not a zip, archives or members over the size caps, too many
files, absolute paths, `..` components, backslashes, drive letters, symbolic links,
encrypted members, extensions outside the allowlist, non-text content, and duplicate names.
Uploaded sources are only ever parsed. They are never compiled or executed (ADR-035).
"""

import hashlib
import io
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.core.config import Settings
from app.core.errors import ApiError

KINDS = {".cbl": "PROGRAM", ".cob": "PROGRAM", ".cpy": "COPYBOOK", ".txt": "DATA_LAYOUT"}
MAX_PATH_LENGTH = 200


@dataclass(frozen=True)
class UploadedSource:
    path: str
    kind: str
    content: str
    sha256: str


def _reject(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


def _safe_path(name: str) -> str:
    if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":") or "\0" in name:
        raise _reject("UPLOAD_PATH_REJECTED", "Archive paths must be relative, with forward slashes only.")
    path = PurePosixPath(name)
    if any(part in {"..", "."} for part in path.parts) or len(name) > MAX_PATH_LENGTH or not path.parts:
        raise _reject("UPLOAD_PATH_REJECTED", "Archive paths may not leave the archive or be this long.")
    return path.as_posix()


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, settings: Settings) -> tuple[str, bytes]:
    path = _safe_path(info.filename)
    if stat.S_ISLNK(info.external_attr >> 16):
        raise _reject("UPLOAD_PATH_REJECTED", "Symbolic links are not accepted.")
    if info.flag_bits & 0x1:
        raise _reject("UPLOAD_ENCRYPTED", "Encrypted archives are not accepted.")
    if PurePosixPath(path).suffix.lower() not in KINDS:
        raise _reject("UPLOAD_TYPE_REJECTED", "Only .cbl, .cob, .cpy and .txt files are accepted.")
    # Read at most one byte past the cap, so a member that lies about its size still stops.
    with archive.open(info) as member:
        body = member.read(settings.upload_max_file_bytes + 1)
    if len(body) > settings.upload_max_file_bytes:
        raise _reject("UPLOAD_TOO_LARGE", f"A file is larger than {settings.upload_max_file_bytes} bytes.")
    return path, body


def _text(body: bytes) -> str:
    try:
        content = body.decode("ascii")
    except UnicodeDecodeError:
        raise _reject("UPLOAD_NOT_TEXT", "Sources must be plain ASCII text.") from None
    if any(ord(char) < 32 and char not in "\n\r\t" for char in content):
        raise _reject("UPLOAD_NOT_TEXT", "Sources must be plain ASCII text.")
    return content.replace("\r\n", "\n")


def read_upload(data: bytes, settings: Settings) -> list[UploadedSource]:
    if len(data) > settings.upload_max_bytes:
        raise _reject("UPLOAD_TOO_LARGE", f"The archive is larger than {settings.upload_max_bytes} bytes.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _reject("UPLOAD_NOT_ZIP", "The upload is not a zip archive.") from None
    members = [info for info in archive.infolist() if not info.is_dir()]
    if not members:
        raise _reject("UPLOAD_EMPTY", "The archive holds no files.")
    if len(members) > settings.upload_max_files:
        raise _reject("UPLOAD_TOO_MANY_FILES", f"The archive holds more than {settings.upload_max_files} files.")
    sources: list[UploadedSource] = []
    names: set[str] = set()
    total = 0
    for info in members:
        path, body = _read_member(archive, info, settings)
        total += len(body)
        if total > settings.upload_max_total_bytes:
            raise _reject("UPLOAD_TOO_LARGE", "The files together are over the size limit.")
        content = _text(body)
        name = PurePosixPath(path).name.upper()
        if name in names:
            raise _reject("UPLOAD_DUPLICATE_NAME", "Two files in the archive have the same name.")
        names.add(name)
        kind = KINDS[PurePosixPath(path).suffix.lower()]
        sources.append(UploadedSource(path, kind, content, hashlib.sha256(content.encode()).hexdigest()))
    if not any(source.kind == "PROGRAM" for source in sources):
        raise _reject("UPLOAD_NO_PROGRAMS", "The archive holds no COBOL program (.cbl or .cob).")
    return sorted(sources, key=lambda source: source.path)
