"""Immutable local document store (CP12H.NL4D5A1a; DEC-D4, D4a-c, Local Test MVP).

An isolated filesystem foundation. It writes no database row, authorizes no
Merchant command and creates no pending confirmation; nothing in the Merchant
execution path calls it yet.

Layout (both roots come only from local configuration, never from a model):

    MERCHANT_DOCUMENT_INBOX/<file name>              user-placed source files
    MERCHANT_DOCUMENT_STORE/staging/ingest-*.part    unique temporary copies
    MERCHANT_DOCUMENT_STORE/objects/sha256/<aa>/<hex> immutable content objects

Guarantees:

- A file is named only by a narrowly validated bare file name inside the
  inbox; paths, traversal, alternate data streams, reserved Windows names,
  symlinks, junctions/reparse points, hard links and special objects are
  refused.
- The SHA-256 is computed by this code from the bytes it copied (streamed,
  bounded memory); an external hash is only ever a value that must match.
- The staged copy is flushed, re-hashed from disk and format-validated before
  promotion. Promotion never overwrites: an existing object is re-verified
  and reused, or reported as an integrity failure.
- Finalized objects are read-only and never modified or deleted by this
  module. Only this module's own temporary staging files are removed, and
  only explicitly.

Not guaranteed (documented in the NL4D5A1a report): filesystem/PostgreSQL
atomicity; directory-entry durability on Windows (directories cannot be
fsynced there); protection against a same-user process that rewrites a file
in place while preserving its size and modification time; full security
scanning of document content (no parsing beyond conservative structure
checks, nothing is rendered or executed).
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import struct
import time
import unicodedata
import uuid
import zipfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

INBOX_ENV = "MERCHANT_DOCUMENT_INBOX"
STORE_ENV = "MERCHANT_DOCUMENT_STORE"

MAX_BYTES = 26_214_400  # DEC-D4b: 25 MiB
CHUNK = 1024 * 1024
# Bounded wait for a transient Windows sharing violation on a just-promoted object.
# Staging files younger than this are never swept (an active ingestion can stall
# on antivirus or slow disks; one hour is far beyond any 25 MiB copy).
MIN_SWEEP_AGE_SECONDS = 3600
SHARING_RETRY_SECONDS = 2.0
STAGING_DIR = "staging"
OBJECTS_DIR = "objects"
HASH_DIR = "sha256"
STAGING_PREFIX = "ingest-"
STAGING_SUFFIX = ".part"

# DEC-D4b: extension -> verified type.
EXTENSIONS = {".pdf": "PDF", ".docx": "DOCX", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
MEDIA_TYPES = {
    "PDF": "application/pdf",
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "PNG": "image/png",
    "JPEG": "image/jpeg",
}

# DOCX archive limits (zip-bomb and unsafe-archive defence).
DOCX_MAX_MEMBERS = 2000
DOCX_MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024
DOCX_MAX_RATIO = 200
DOCX_MAIN_TYPE = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{p}{n}" for p in ("COM", "LPT") for n in list("0123456789") + ["¹", "²", "³"]
}
_FORBIDDEN_CHARS = set('<>:"/\\|?*')
_HEX64 = re.compile(r"[0-9a-f]{64}")
_OPEN_READ = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)

# Reasons (stable codes for callers and tests).
CONFIG_INVALID = "CONFIG_INVALID"
IDENTIFIER_INVALID = "IDENTIFIER_INVALID"
EXTENSION_UNSUPPORTED = "EXTENSION_UNSUPPORTED"
NOT_FOUND = "NOT_FOUND"
NOT_REGULAR_FILE = "NOT_REGULAR_FILE"
REPARSE_POINT = "REPARSE_POINT"
HARD_LINKED = "HARD_LINKED"
EMPTY_FILE = "EMPTY_FILE"
TOO_LARGE = "TOO_LARGE"
FORMAT_INVALID = "FORMAT_INVALID"
SOURCE_CHANGED = "SOURCE_CHANGED"
CONTENT_MISMATCH = "CONTENT_MISMATCH"
HASH_MISMATCH = "HASH_MISMATCH"
FLUSH_FAILED = "FLUSH_FAILED"
PROMOTION_FAILED = "PROMOTION_FAILED"
INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
PERMISSION_DENIED = "PERMISSION_DENIED"

# Inventory classes.
VERIFIED_REFERENCED = "VERIFIED_REFERENCED"
ORPHANED_FINALIZED = "ORPHANED_FINALIZED"
CORRUPT_STORED = "CORRUPT_STORED"
INCOMPLETE_STAGING = "INCOMPLETE_STAGING"
UNEXPECTED_ENTRY = "UNEXPECTED_ENTRY"


class DocumentStoreError(Exception):
    """A refused or failed storage operation; ``reason`` is a stable code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class StoredObject:
    """Trusted immutable metadata of one verified stored object."""

    object_id: str          # "sha256:<hex>"
    sha256: str
    storage_key: str        # "sha256/<aa>/<hex>", relative to objects/
    byte_size: int
    file_type: str          # PDF | DOCX | PNG | JPEG (verified)
    media_type: str
    original_name: str      # sanitized metadata only; never a path
    integrity: str          # "VERIFIED"
    reused: bool            # identical bytes were already stored

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InspectedFile:
    """Read-only facts about an inbox file (no copy, nothing written)."""

    original_name: str
    sha256: str
    byte_size: int
    file_type: str
    media_type: str


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    classification: str
    sha256: str | None = None
    detail: str = ""


# --------------------------------------------------------------- configuration


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _inside(child: Path, parent: Path) -> bool:
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _is_reparse_or_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _checked_directory(raw: object, name: str) -> Path:
    if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
        raise DocumentStoreError(CONFIG_INVALID, f"{name} is not set")
    path = Path(raw)
    if not path.is_absolute() or raw.startswith("\\\\"):
        raise DocumentStoreError(CONFIG_INVALID, f"{name} must be an absolute local path")
    try:
        st = os.lstat(path)
    except OSError as error:
        raise DocumentStoreError(CONFIG_INVALID, f"{name} does not exist") from error
    if _is_reparse_or_link(st) or not stat.S_ISDIR(st.st_mode):
        raise DocumentStoreError(CONFIG_INVALID, f"{name} must be a real directory")
    # A junction or symlink anywhere in the ancestry resolves elsewhere.
    if _norm(Path(os.path.realpath(path))) != _norm(path):
        raise DocumentStoreError(CONFIG_INVALID, f"{name} must not pass through a link")
    return Path(os.path.normpath(str(path)))


def _require_real_directory(path: Path) -> None:
    """The actual filesystem object must be a directory, not a link or junction."""
    try:
        st = os.lstat(path)
    except OSError as error:
        raise DocumentStoreError(CONFIG_INVALID, f"{path.name} is unavailable") from error
    if _is_reparse_or_link(st) or not stat.S_ISDIR(st.st_mode):
        raise DocumentStoreError(CONFIG_INVALID, f"{path.name} must be a real directory")


def _sync_roots(environ: Mapping[str, str]) -> list[Path]:
    roots = []
    for key in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        value = environ.get(key)
        if value:
            roots.append(Path(value))
    return roots


@dataclass(frozen=True)
class StoreConfig:
    """Validated inbox and store roots (DEC-D4a)."""

    inbox: Path
    store: Path

    @property
    def staging(self) -> Path:
        return self.store / STAGING_DIR

    @property
    def objects(self) -> Path:
        return self.store / OBJECTS_DIR

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None,
                 repository_root: Path | None = None) -> "StoreConfig":
        environ = os.environ if environ is None else environ
        return cls.validated(environ.get(INBOX_ENV), environ.get(STORE_ENV),
                             repository_root=repository_root, environ=environ)

    @classmethod
    def validated(cls, inbox: object, store: object, *, repository_root: Path | None = None,
                  environ: Mapping[str, str] | None = None) -> "StoreConfig":
        """Refuse an invalid configuration; create only staging/ and objects/ under the store."""

        inbox_path = _checked_directory(inbox, INBOX_ENV)
        store_path = _checked_directory(store, STORE_ENV)
        repo = repository_root or _repository_root()
        for path, name in ((inbox_path, INBOX_ENV), (store_path, STORE_ENV)):
            if _inside(path, repo) or _inside(repo, path):
                raise DocumentStoreError(CONFIG_INVALID, f"{name} must be outside the repository")
            for sync_root in _sync_roots(os.environ if environ is None else environ):
                if _inside(path, sync_root):
                    raise DocumentStoreError(CONFIG_INVALID, f"{name} must not be in a sync folder")
        if _inside(inbox_path, store_path) or _inside(store_path, inbox_path):
            raise DocumentStoreError(CONFIG_INVALID, "inbox and store must be separate trees")

        config = cls(inbox_path, store_path)
        for sub in (config.staging, config.objects, config.objects / HASH_DIR):
            try:
                os.mkdir(sub)
            except FileExistsError:
                pass
            except OSError as error:
                raise DocumentStoreError(CONFIG_INVALID, f"cannot prepare {sub.name}") from error
            _require_real_directory(sub)
        # Atomic promotion requires staging and objects on one filesystem.
        if os.stat(config.staging).st_dev != os.stat(config.objects).st_dev:
            raise DocumentStoreError(CONFIG_INVALID, "staging and objects are on different volumes")
        return config


# ------------------------------------------------------------- identifiers


def validate_file_name(file_name: object) -> str:
    """The one accepted identifier: a bare inbox file name (also the sanitized metadata)."""

    if not isinstance(file_name, str) or not file_name or len(file_name) > 200:
        raise DocumentStoreError(IDENTIFIER_INVALID, "a bare file name of 1-200 characters")
    if unicodedata.normalize("NFC", file_name) != file_name:
        raise DocumentStoreError(IDENTIFIER_INVALID, "the file name must be NFC normalized")
    if file_name in (".", "..") or file_name != file_name.strip() or file_name.endswith("."):
        raise DocumentStoreError(IDENTIFIER_INVALID, "no dot-only, padded or dot-ending names")
    for char in file_name:
        if char in _FORBIDDEN_CHARS or unicodedata.category(char)[0] == "C":
            raise DocumentStoreError(
                IDENTIFIER_INVALID, "no path separators, streams, wildcards or control characters")
    if file_name.split(".")[0].upper().rstrip() in _RESERVED:
        raise DocumentStoreError(IDENTIFIER_INVALID, "reserved Windows device name")
    if Path(file_name).suffix.lower() not in EXTENSIONS:
        raise DocumentStoreError(EXTENSION_UNSUPPORTED, "only .pdf, .docx, .png, .jpg, .jpeg")
    return file_name


def _declared_type(file_name: str) -> str:
    return EXTENSIONS[Path(file_name).suffix.lower()]


def _resolve_source(config: StoreConfig, file_name: object) -> tuple[str, Path, os.stat_result]:
    name = validate_file_name(file_name)
    path = config.inbox / name
    try:
        st = os.lstat(path)
    except FileNotFoundError as error:
        raise DocumentStoreError(NOT_FOUND, "no such file in the inbox") from error
    except PermissionError as error:
        raise DocumentStoreError(PERMISSION_DENIED, "inbox file not readable") from error
    if _is_reparse_or_link(st):
        raise DocumentStoreError(REPARSE_POINT, "symlinks, junctions and reparse points are refused")
    if not stat.S_ISREG(st.st_mode):
        raise DocumentStoreError(NOT_REGULAR_FILE, "only regular files are accepted")
    if st.st_nlink != 1:
        raise DocumentStoreError(HARD_LINKED, "hard-linked files are refused")
    if _norm(Path(os.path.realpath(path)).parent) != _norm(config.inbox):
        raise DocumentStoreError(REPARSE_POINT, "the file resolves outside the inbox")
    if st.st_size == 0:
        raise DocumentStoreError(EMPTY_FILE)
    if st.st_size > MAX_BYTES:
        raise DocumentStoreError(TOO_LARGE, f"more than {MAX_BYTES} bytes")
    return name, path, st


def _same_object(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_ino, a.st_dev, a.st_size, a.st_mtime_ns) == (b.st_ino, b.st_dev, b.st_size, b.st_mtime_ns)


# ------------------------------------------------------------------ hashing


def _open_stored(path: Path) -> int:
    """Open a stored object for reading.

    On Windows a file that another thread or process has just renamed into
    place can briefly refuse new handles (a sharing violation, surfaced as
    PermissionError). Retry for a bounded time, then report it; never repair.
    """
    deadline = time.monotonic() + SHARING_RETRY_SECONDS
    while True:
        try:
            return os.open(path, _OPEN_READ)
        except PermissionError as error:
            if time.monotonic() >= deadline:
                raise DocumentStoreError(PERMISSION_DENIED, "stored object could not be opened") from error
            time.sleep(0.01)


def _hash_path(path: Path, limit: int | None = MAX_BYTES, *, stored: bool = False) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    fd = _open_stored(path) if stored else os.open(path, _OPEN_READ)
    try:
        while True:
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if limit is not None and size > limit:
                raise DocumentStoreError(TOO_LARGE, f"more than {limit} bytes")
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest(), size


# --------------------------------------------------------- format validation


def _bad(detail: str) -> DocumentStoreError:
    return DocumentStoreError(FORMAT_INVALID, detail)


def _validate_pdf(data: bytes) -> None:
    """Conservative structure only: header, version, xref pointer and EOF marker.
    Not a security scan; content is never parsed further or rendered."""
    if not re.match(rb"%PDF-[12]\.\d", data[:16]):
        raise _bad("missing PDF header")
    tail = data[-2048:]
    if b"%%EOF" not in tail or b"startxref" not in tail:
        raise _bad("missing PDF trailer (startxref / %%EOF)")
    if b" obj" not in data and b"\nobj" not in data:
        raise _bad("no PDF objects")


def _validate_png(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise _bad("missing PNG signature")
    position, first, seen_idat = 8, True, False
    while True:
        if position + 8 > len(data):
            raise _bad("truncated PNG chunk")
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        if length > 0x7FFFFFFF or not kind.isalpha():
            raise _bad("invalid PNG chunk header")
        end = position + 8 + length + 4
        if end > len(data):
            raise _bad("truncated PNG chunk data")
        body = data[position + 4:position + 8 + length]
        (crc,) = struct.unpack(">I", data[position + 8 + length:end])
        if zlib.crc32(body) & 0xFFFFFFFF != crc:
            raise _bad("PNG chunk CRC mismatch")
        if first:
            if kind != b"IHDR" or length != 13:
                raise _bad("PNG must start with IHDR")
            width, height = struct.unpack(">II", data[position + 8:position + 16])
            if not (0 < width <= 100_000 and 0 < height <= 100_000):
                raise _bad("PNG dimensions out of range")
            first = False
        seen_idat |= kind == b"IDAT"
        position = end
        if kind == b"IEND":
            if position != len(data):
                raise _bad("data after PNG IEND")
            if not seen_idat:
                raise _bad("PNG has no image data")
            return


def _validate_jpeg(data: bytes) -> None:
    if not data.startswith(b"\xff\xd8\xff"):
        raise _bad("missing JPEG SOI")
    position, seen_frame, seen_scan = 2, False, False
    while True:
        if position + 2 > len(data) or data[position] != 0xFF:
            raise _bad("invalid JPEG marker")
        while position < len(data) and data[position] == 0xFF:  # fill bytes
            position += 1
        if position >= len(data):
            raise _bad("truncated JPEG")
        marker = data[position]
        position += 1
        if marker == 0xD9:  # EOI
            if position != len(data):
                raise _bad("data after JPEG EOI")
            if not (seen_frame and seen_scan):
                raise _bad("JPEG without frame or scan")
            return
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(data):
            raise _bad("truncated JPEG segment")
        (length,) = struct.unpack(">H", data[position:position + 2])
        if length < 2 or position + length > len(data):
            raise _bad("JPEG segment length out of range")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            seen_frame = True
        position += length
        if marker == 0xDA:  # SOS: skip entropy-coded data to the next real marker
            if not seen_frame:
                raise _bad("JPEG scan before frame")
            seen_scan = True
            while True:
                index = data.find(b"\xff", position)
                if index < 0 or index + 1 >= len(data):
                    raise _bad("JPEG scan not terminated")
                following = data[index + 1]
                if following == 0x00 or 0xD0 <= following <= 0xD7 or following == 0xFF:
                    position = index + (2 if following != 0xFF else 1)
                    continue
                position = index
                break


def _safe_member_name(name: str) -> bool:
    if not name or len(name) > 512 or "\\" in name or name.startswith("/") or ":" in name:
        return False
    if any(unicodedata.category(c)[0] == "C" for c in name):
        return False
    parts = name.rstrip("/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _validate_docx(path: Path) -> None:
    """OOXML package checks; nothing is extracted to disk, nothing is executed."""
    if not zipfile.is_zipfile(path):
        raise _bad("not a ZIP package")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > DOCX_MAX_MEMBERS:
                raise _bad("too many archive members")
            names = set()
            declared_total = 0
            for info in members:
                if not _safe_member_name(info.filename):
                    raise _bad("unsafe archive member name")
                if info.filename.lower() in names:
                    raise _bad("duplicate archive member")
                names.add(info.filename.lower())
                if info.flag_bits & 0x1:
                    raise _bad("encrypted archive member")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise _bad("unsupported compression")
                declared_total += info.file_size
                if info.compress_size and info.file_size / info.compress_size > DOCX_MAX_RATIO:
                    raise _bad("compression ratio too high")
            if declared_total > DOCX_MAX_TOTAL_UNCOMPRESSED:
                raise _bad("declared uncompressed size too large")
            for required in ("[content_types].xml", "_rels/.rels", "word/document.xml"):
                if required not in names:
                    raise _bad(f"missing {required}")
            if "word/vbaproject.bin" in names:
                raise _bad("macro project present")
            # Stream every member with an actual-bytes cap: catches headers that
            # lie about sizes, and verifies each member's CRC.
            actual_total, content_types = 0, b""
            for info in members:
                if info.is_dir():
                    continue
                with archive.open(info) as member:
                    while True:
                        chunk = member.read(CHUNK)
                        if not chunk:
                            break
                        actual_total += len(chunk)
                        if actual_total > DOCX_MAX_TOTAL_UNCOMPRESSED:
                            raise _bad("archive expands beyond the limit")
                        if info.filename.lower() == "[content_types].xml":
                            content_types += chunk
                            if len(content_types) > 1024 * 1024:
                                raise _bad("[Content_Types].xml too large")
            if DOCX_MAIN_TYPE not in content_types:
                raise _bad("not a WordprocessingML document")
            if b"macroEnabled" in content_types:
                raise _bad("macro-enabled document")
    except DocumentStoreError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError,
            NotImplementedError, RuntimeError, zlib.error) as error:
        raise _bad(f"corrupt archive ({type(error).__name__})") from error


def validate_format(path: Path, declared_type: str) -> str:
    """Verify the content structure agrees with the declared type; return it."""

    if declared_type == "DOCX":
        _validate_docx(path)
        return declared_type
    with open(path, "rb") as handle:  # bounded: callers enforce MAX_BYTES first
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise DocumentStoreError(TOO_LARGE)
    {"PDF": _validate_pdf, "PNG": _validate_png, "JPEG": _validate_jpeg}[declared_type](data)
    return declared_type


# ---------------------------------------------------------------- inspection


def inspect(config: StoreConfig, file_name: object) -> InspectedFile:
    """Read-only: validate, type-check and hash an inbox file. Writes nothing."""

    name, path, before = _resolve_source(config, file_name)
    declared = _declared_type(name)
    validate_format(path, declared)
    sha256, size = _hash_path(path)
    after = os.lstat(path)
    if not _same_object(before, after) or size != before.st_size:
        raise DocumentStoreError(SOURCE_CHANGED, "the inbox file changed while it was read")
    return InspectedFile(name, sha256, size, declared, MEDIA_TYPES[declared])


# ------------------------------------------------------------------ ingestion


def _fsync(fd: int) -> None:
    os.fsync(fd)


def _promote_no_overwrite(source: Path, destination: Path) -> None:
    """Atomically create ``destination`` from ``source``; never replace an existing file."""
    if os.name == "nt":
        os.rename(source, destination)  # MoveFileEx without REPLACE_EXISTING
    else:  # pragma: no cover - the MVP runs on Windows
        os.link(source, destination)
        os.unlink(source)


def _remove_own_staging(path: Path) -> None:
    """Remove a temporary staging file this call created (never anything else)."""
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        os.unlink(path)
    except FileNotFoundError:
        pass


def object_path(config: StoreConfig, sha256: str) -> Path:
    if not isinstance(sha256, str) or not _HEX64.fullmatch(sha256):
        raise DocumentStoreError(IDENTIFIER_INVALID, "sha256 must be 64 lowercase hex")
    return config.objects / HASH_DIR / sha256[:2] / sha256


def _verify_existing(path: Path, sha256: str, size: int) -> None:
    try:
        st = os.lstat(path)
        if _is_reparse_or_link(st) or not stat.S_ISREG(st.st_mode):
            raise DocumentStoreError(INTEGRITY_FAILURE, "stored object is not a regular file")
        actual, actual_size = _hash_path(path, limit=None, stored=True)
    except FileNotFoundError as error:  # for example quarantined by antivirus
        raise DocumentStoreError(INTEGRITY_FAILURE, "stored object is missing") from error
    if actual != sha256 or actual_size != size:
        raise DocumentStoreError(INTEGRITY_FAILURE, "stored object bytes do not match its identity")


def ingest(config: StoreConfig, file_name: object, *, expected_sha256: str | None = None) -> StoredObject:
    """Copy one inbox file into immutable storage and return verified metadata.

    ``expected_sha256`` (from a trusted preview, NL4D5A2+) is a constraint the
    copied bytes must satisfy, never a substitute for hashing them.
    """

    # The store directories are re-checked on the actual filesystem objects at
    # every operation, not only when the configuration was validated.
    for directory in (config.staging, config.objects, config.objects / HASH_DIR):
        _require_real_directory(directory)
    name, source, before = _resolve_source(config, file_name)
    declared = _declared_type(name)
    staged = config.staging / f"{STAGING_PREFIX}{uuid.uuid4().hex}{STAGING_SUFFIX}"
    created = False
    try:
        try:
            source_fd = os.open(source, _OPEN_READ)
        except PermissionError as error:
            raise DocumentStoreError(PERMISSION_DENIED, "inbox file not readable") from error
        try:
            if not _same_object(before, os.fstat(source_fd)):
                raise DocumentStoreError(SOURCE_CHANGED, "the inbox entry was replaced before opening")
            try:
                staged_fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                    | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0), 0o600)
            except PermissionError as error:
                raise DocumentStoreError(PERMISSION_DENIED, "staging not writable") from error
            created = True
            digest, size = hashlib.sha256(), 0
            try:
                while True:
                    chunk = _read_chunk(source_fd)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise DocumentStoreError(TOO_LARGE, f"more than {MAX_BYTES} bytes")
                    digest.update(chunk)
                    _write_all(staged_fd, chunk)
                try:
                    _fsync(staged_fd)
                except OSError as error:
                    raise DocumentStoreError(FLUSH_FAILED, "staged bytes could not be flushed") from error
            finally:
                os.close(staged_fd)
            if not _same_object(before, os.fstat(source_fd)) or size != before.st_size:
                raise DocumentStoreError(SOURCE_CHANGED, "the inbox file changed during the copy")
        finally:
            os.close(source_fd)
        try:
            if not _same_object(before, os.lstat(source)):
                raise DocumentStoreError(SOURCE_CHANGED, "the inbox entry changed after the copy")
        except FileNotFoundError as error:
            raise DocumentStoreError(SOURCE_CHANGED, "the inbox entry disappeared") from error

        sha256 = digest.hexdigest()
        try:
            rehashed, staged_size = _hash_path(staged)
            if rehashed != sha256 or staged_size != size:
                raise DocumentStoreError(HASH_MISMATCH, "staged bytes differ from the bytes copied")
            if expected_sha256 is not None and sha256 != expected_sha256:
                raise DocumentStoreError(CONTENT_MISMATCH, "the file is not the previewed content")
            validate_format(staged, declared)  # the trusted copy, not the source

            destination = object_path(config, sha256)
            try:
                os.mkdir(destination.parent)
            except FileExistsError:
                pass
            parent = os.lstat(destination.parent)
            if _is_reparse_or_link(parent) or not stat.S_ISDIR(parent.st_mode):
                raise DocumentStoreError(INTEGRITY_FAILURE, "object directory is not a real directory")
            os.chmod(staged, stat.S_IREAD)  # immutable before it becomes visible
        except FileNotFoundError as error:
            raise DocumentStoreError(INTEGRITY_FAILURE, "the staged copy disappeared") from error
        reused = False
        try:
            _promote_no_overwrite(staged, destination)
            created = False  # the staging name no longer exists
        except FileExistsError:
            _verify_existing(destination, sha256, size)  # reuse only verified bytes
            reused = True
        except OSError as error:
            raise DocumentStoreError(PROMOTION_FAILED, type(error).__name__) from error

        _verify_existing(destination, sha256, size)
        return StoredObject(
            object_id=f"sha256:{sha256}", sha256=sha256,
            storage_key=f"{HASH_DIR}/{sha256[:2]}/{sha256}", byte_size=size,
            file_type=declared, media_type=MEDIA_TYPES[declared], original_name=name,
            integrity="VERIFIED", reused=reused,
        )
    finally:
        if created:
            _remove_own_staging(staged)


def _read_chunk(fd: int) -> bytes:
    return os.read(fd, CHUNK)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


# ------------------------------------------------- verification and inventory


def verify_object(config: StoreConfig, sha256: str) -> str:
    """Re-hash a stored object: VERIFIED, MISSING or CORRUPT. Never repairs."""

    path = object_path(config, sha256)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "MISSING"
    if _is_reparse_or_link(st) or not stat.S_ISREG(st.st_mode):
        return "CORRUPT"
    try:
        actual, _ = _hash_path(path, limit=None, stored=True)
    except FileNotFoundError:
        return "MISSING"
    return "VERIFIED" if actual == sha256 else "CORRUPT"


def inventory(config: StoreConfig, referenced: Iterable[str] = ()) -> list[InventoryEntry]:
    """Classify every store entry against an authoritative reference set
    (sha256 hex or ``sha256:<hex>``). Read-only: nothing is deleted or repaired."""

    wanted = {ref.removeprefix("sha256:") for ref in referenced}
    entries: list[InventoryEntry] = []
    with os.scandir(config.staging) as staging:
        for item in staging:
            st = item.stat(follow_symlinks=False)
            ours = (item.name.startswith(STAGING_PREFIX) and item.name.endswith(STAGING_SUFFIX)
                    and stat.S_ISREG(st.st_mode) and not _is_reparse_or_link(st))
            entries.append(InventoryEntry(
                str(Path(STAGING_DIR) / item.name),
                INCOMPLETE_STAGING if ours else UNEXPECTED_ENTRY,
                detail=f"age {int(time.time() - st.st_mtime)}s"))
    root = config.objects / HASH_DIR
    with os.scandir(root) as prefixes:
        for prefix in prefixes:
            pst = prefix.stat(follow_symlinks=False)
            relative = Path(OBJECTS_DIR) / HASH_DIR / prefix.name
            if _is_reparse_or_link(pst) or not stat.S_ISDIR(pst.st_mode) or not re.fullmatch(
                    r"[0-9a-f]{2}", prefix.name):
                entries.append(InventoryEntry(str(relative), UNEXPECTED_ENTRY))
                continue
            with os.scandir(prefix.path) as objects:
                for item in objects:
                    name = item.name
                    if not _HEX64.fullmatch(name) or name[:2] != prefix.name:
                        entries.append(InventoryEntry(str(relative / name), UNEXPECTED_ENTRY))
                        continue
                    state = verify_object(config, name)
                    if state != "VERIFIED":
                        classification = CORRUPT_STORED
                    elif name in wanted:
                        classification = VERIFIED_REFERENCED
                    else:
                        classification = ORPHANED_FINALIZED
                    entries.append(InventoryEntry(str(relative / name), classification, name))
    return entries


def sweep_staging(config: StoreConfig, older_than_seconds: float) -> list[str]:
    """Explicit, narrowly scoped cleanup of abandoned temporary staging files.

    Removes only regular ``ingest-*.part`` files directly in staging/ that are
    older than the threshold (at least MIN_SWEEP_AGE_SECONDS, far beyond any
    live ingestion of a 25 MiB file, so an active operation is never swept; if
    one were, it fails closed). Never touches objects/ (finalized orphans are
    reported by ``inventory`` for manual review, DEC-D4a).
    """

    if older_than_seconds < MIN_SWEEP_AGE_SECONDS:
        raise DocumentStoreError(
            CONFIG_INVALID, f"threshold must be at least {MIN_SWEEP_AGE_SECONDS} seconds")
    removed = []
    cutoff = time.time() - older_than_seconds
    with os.scandir(config.staging) as staging:
        for item in staging:
            st = item.stat(follow_symlinks=False)
            if (item.name.startswith(STAGING_PREFIX) and item.name.endswith(STAGING_SUFFIX)
                    and stat.S_ISREG(st.st_mode) and not _is_reparse_or_link(st)
                    and st.st_mtime < cutoff):
                _remove_own_staging(Path(item.path))
                removed.append(item.name)
    return removed
