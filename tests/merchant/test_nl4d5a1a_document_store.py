"""CP12H.NL4D5A1a: immutable local document store (filesystem only, no database).

Every test uses its own temporary inbox and store outside the repository.
No PostgreSQL connection, Merchant command, pending confirmation or revision
is involved.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import threading
import time
import unicodedata
import zipfile
import zlib
from pathlib import Path

import pytest

from claude.clients.merchant import document_store as ds

# ------------------------------------------------------------------ builders


def pdf(pad: int = 0) -> bytes:
    body = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    tail = b"trailer\n<< /Root 1 0 R >>\nstartxref\n9\n%%EOF\n"
    return body + b"%" + b"0" * pad + b"\n" + tail if pad else body + tail


def png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg() -> bytes:
    return (b"\xff\xd8"
            + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0" + struct.pack(">H", 11) + b"\x08\x00\x02\x00\x02\x01\x01\x11\x00"
            + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"
            + b"\x12\x34\xff\x00\x56\xff\xd0\x78"
            + b"\xff\xd9")


CONTENT_TYPES = (
    b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    b'content-types"><Override PartName="/word/document.xml" ContentType="application/'
    b'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')


def docx(extra: dict[str, bytes] | None = None, drop: str | None = None,
         content_types: bytes = CONTENT_TYPES) -> bytes:
    members = {"[Content_Types].xml": content_types, "_rels/.rels": b"<Relationships/>",
               "word/document.xml": b"<w:document/>", **(extra or {})}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            if name != drop:
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
    return buffer.getvalue()


VALID = {"a.pdf": pdf, "a.png": png, "a.jpg": jpeg, "a.jpeg": jpeg, "a.docx": docx}


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def roots(tmp_path):
    inbox, store = tmp_path / "inbox", tmp_path / "store"
    inbox.mkdir()
    store.mkdir()
    return inbox, store


@pytest.fixture
def config(roots):
    return ds.StoreConfig.validated(str(roots[0]), str(roots[1]), environ={})


def put(config, name, data):
    path = config.inbox / name
    path.write_bytes(data)
    return path


def objects(config):
    return sorted(p for p in (config.objects / ds.HASH_DIR).rglob("*") if p.is_file())


def staging(config):
    return sorted(config.staging.iterdir())


def reason(call, *args, **kwargs):
    with pytest.raises(ds.DocumentStoreError) as error:
        call(*args, **kwargs)
    return error.value.reason


# ------------------------------------------------------------- allowed formats


@pytest.mark.parametrize("name", sorted(VALID))
def test_allowed_formats_are_stored_with_verified_metadata(config, name):
    data = VALID[name]()
    put(config, name, data)

    stored = ds.ingest(config, name)

    sha = hashlib.sha256(data).hexdigest()
    assert (stored.sha256, stored.object_id, stored.byte_size) == (sha, f"sha256:{sha}", len(data))
    assert stored.storage_key == f"sha256/{sha[:2]}/{sha}"
    assert stored.file_type == ds.EXTENSIONS[Path(name).suffix] and stored.integrity == "VERIFIED"
    assert stored.original_name == name and stored.reused is False
    final = ds.object_path(config, sha)
    assert final.read_bytes() == data
    assert not os.stat(final).st_mode & stat.S_IWRITE          # read-only
    assert staging(config) == []
    assert ds.verify_object(config, sha) == "VERIFIED"


def test_inspect_is_read_only_and_agrees_with_ingest(config):
    put(config, "a.pdf", pdf())

    seen = ds.inspect(config, "a.pdf")

    assert objects(config) == [] and staging(config) == []
    assert ds.ingest(config, "a.pdf").sha256 == seen.sha256


# ------------------------------------------------------------------ size limit


def test_exact_25_mib_is_accepted_and_one_byte_more_is_refused(config):
    base = len(pdf(pad=1)) - 1
    exact = pdf(pad=ds.MAX_BYTES - base)
    assert len(exact) == ds.MAX_BYTES == 26_214_400
    put(config, "max.pdf", exact)
    put(config, "over.pdf", pdf(pad=ds.MAX_BYTES - base + 1))

    assert ds.ingest(config, "max.pdf").byte_size == ds.MAX_BYTES
    assert reason(ds.ingest, config, "over.pdf") == ds.TOO_LARGE
    assert reason(ds.inspect, config, "over.pdf") == ds.TOO_LARGE


def test_empty_files_are_refused(config):
    put(config, "e.pdf", b"")

    assert reason(ds.ingest, config, "e.pdf") == ds.EMPTY_FILE


def test_a_file_growing_past_the_limit_during_copy_is_refused(config, monkeypatch):
    path = put(config, "g.pdf", pdf())
    real = ds._read_chunk

    def grow(fd):
        with open(path, "ab") as handle:
            handle.write(b"0" * (ds.MAX_BYTES + 1))
        monkeypatch.setattr(ds, "_read_chunk", real)
        return real(fd)

    monkeypatch.setattr(ds, "_read_chunk", grow)

    assert reason(ds.ingest, config, "g.pdf") in (ds.TOO_LARGE, ds.SOURCE_CHANGED)
    assert objects(config) == [] and staging(config) == []


# ---------------------------------------------------- extension vs signature


@pytest.mark.parametrize("name,data", [
    ("a.pdf", png()), ("a.png", pdf()), ("a.jpg", png()), ("a.docx", pdf()),
    ("a.png", jpeg()), ("a.jpeg", b"GIF89a" + b"\x00" * 20), ("a.pdf", b"%PDX-1.4 not a pdf"),
])
def test_spoofed_signatures_and_wrong_extensions_are_refused(config, name, data):
    put(config, name, data)

    assert reason(ds.ingest, config, name) == ds.FORMAT_INVALID
    assert objects(config) == [] and staging(config) == []


@pytest.mark.parametrize("name", ["a.exe", "a.docm", "a.pdf.exe", "a.txt", "a.zip", "a"])
def test_unsupported_extensions_are_refused(config, name):
    assert reason(ds.ingest, config, name) == ds.EXTENSION_UNSUPPORTED


# ------------------------------------------------------- corrupt PDF/PNG/JPEG


def _bad_crc_png():
    data = bytearray(png())
    data[33 + 10] ^= 0xFF                                   # inside IDAT
    return bytes(data)


@pytest.mark.parametrize("name,data", [
    ("a.pdf", pdf().replace(b"%%EOF", b"%%EOX")),
    ("a.pdf", pdf().replace(b"startxref", b"startxrex")),
    ("a.png", _bad_crc_png()),
    ("a.png", png()[:-6]),                                   # truncated
    ("a.png", png() + b"trailing"),
    ("a.jpg", jpeg()[:-2]),                                  # no EOI
    ("a.jpg", jpeg() + b"junk"),
    ("a.jpg", b"\xff\xd8\xff\xe0\xff\xff" + b"\x00" * 8),    # bad segment length
])
def test_corrupt_images_and_pdfs_are_refused(config, name, data):
    put(config, name, data)

    assert reason(ds.ingest, config, name) == ds.FORMAT_INVALID


# ----------------------------------------------------------------- DOCX


def _raw_name_zip(name: str) -> bytes:
    """A ZIP whose member name is written verbatim (zipfile would normalize some)."""
    buffer = io.BytesIO(docx())
    data = buffer.getvalue().replace(b"word/document.xml", name.encode().ljust(17, b"x")[:17])
    return data


@pytest.mark.parametrize("data,label", [
    (docx(drop="word/document.xml"), "missing document part"),
    (docx(drop="[Content_Types].xml"), "missing content types"),
    (docx(content_types=b"<Types/>"), "not WordprocessingML"),
    (docx(content_types=CONTENT_TYPES.replace(b"document.main", b"document.macroEnabled.main")),
     "macro-enabled"),
    (docx(extra={"word/vbaProject.bin": b"\x00"}), "macro project"),
    (docx()[:-30], "truncated archive"),
    (b"PK\x03\x04" + b"\x00" * 64, "garbage ZIP"),
])
def test_malformed_docx_packages_are_refused(config, data, label):
    put(config, "a.docx", data)

    assert reason(ds.ingest, config, "a.docx") == ds.FORMAT_INVALID, label


@pytest.mark.parametrize("member", ["../evil.xml", "/abs/evil.xml", "C:evil.xml", "word/../../x.xml",
                                    "a\\b.xml"])
def test_malicious_zip_member_names_are_refused_and_nothing_is_extracted(config, member, tmp_path):
    data = docx(extra={member: b"x"}) if "\\" not in member else _raw_name_zip("a\\b.xml")
    put(config, "a.docx", data)

    assert reason(ds.ingest, config, "a.docx") == ds.FORMAT_INVALID
    assert not (tmp_path / "evil.xml").exists() and not Path("C:evil.xml").exists()


def test_zip_bombs_are_refused(config):
    bomb = docx(extra={"word/media/bomb.bin": b"\x00" * (60 * 1024 * 1024)})
    assert len(bomb) < ds.MAX_BYTES                          # small on disk
    put(config, "a.docx", bomb)

    assert reason(ds.ingest, config, "a.docx") == ds.FORMAT_INVALID


def test_a_bomb_with_lying_size_headers_is_refused(config):
    """Central directory understates the size to pass the ratio check; the
    streamed, CRC-checked read still refuses it."""
    data = bytearray(docx(extra={"word/media/b.bin": b"\x00" * (10 * 1024 * 1024)}))
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as archive:
        info = archive.getinfo("word/media/b.bin")
    entry = data.find(b"PK\x01\x02")
    while entry >= 0:
        name_len = struct.unpack("<H", data[entry + 28:entry + 30])[0]
        if data[entry + 46:entry + 46 + name_len] == b"word/media/b.bin":
            data[entry + 24:entry + 28] = struct.pack("<I", info.compress_size)   # lie
            break
        entry = data.find(b"PK\x01\x02", entry + 4)
    put(config, "a.docx", bytes(data))

    with pytest.raises(ds.DocumentStoreError) as error:
        ds.ingest(config, "a.docx")
    assert error.value.reason == ds.FORMAT_INVALID
    assert "ratio" not in str(error.value)                    # caught by the streamed read


def test_too_many_members_is_refused(config):
    put(config, "a.docx", docx(extra={f"word/p{i}.xml": b"x" for i in range(ds.DOCX_MAX_MEMBERS)}))

    assert reason(ds.ingest, config, "a.docx") == ds.FORMAT_INVALID


def test_an_encrypted_member_is_refused(config):
    data = bytearray(docx())
    # Set the general-purpose "encrypted" bit in every central directory entry.
    index = 0
    while (index := data.find(b"PK\x01\x02", index)) >= 0:
        data[index + 8] |= 0x01
        index += 4
    put(config, "a.docx", bytes(data))

    assert reason(ds.ingest, config, "a.docx") == ds.FORMAT_INVALID


# --------------------------------------------------------- identifiers / paths


@pytest.mark.parametrize("name", [
    "../a.pdf", "..\\a.pdf", "C:\\x\\a.pdf", "C:a.pdf", "\\\\server\\share\\a.pdf", "dir/a.pdf",
    "a.pdf:evil", "a.pdf::$DATA", "a\x00.pdf", "a\n.pdf", "*.pdf", "a?.pdf", "a.pdf.", "a.pdf ",
    " a.pdf", ".", "..", "", "x" * 201 + ".pdf", 42, None,
])
def test_path_traversal_streams_and_unsafe_identifiers_are_refused(config, name):
    assert reason(ds.ingest, config, name) in (ds.IDENTIFIER_INVALID, ds.EXTENSION_UNSUPPORTED)


@pytest.mark.parametrize("name", ["CON.pdf", "nul.docx", "COM1.png", "lpt9.jpg", "aux.pdf",
                                  "Com3.jpeg", "CONIN$.pdf"])
def test_reserved_windows_names_are_refused(config, name):
    assert reason(ds.ingest, config, name) == ds.IDENTIFIER_INVALID


def test_unicode_names_are_metadata_only_and_must_be_nfc(config):
    name = "Hợp đồng Nguyễn Văn Cừ.pdf"
    put(config, name, pdf())

    stored = ds.ingest(config, name)

    assert stored.original_name == name
    assert name not in stored.storage_key                    # never a path
    assert reason(ds.ingest, config, unicodedata.normalize("NFD", name)) == ds.IDENTIFIER_INVALID


def test_missing_files_and_directories_are_refused(config):
    (config.inbox / "d.pdf").mkdir()

    assert reason(ds.ingest, config, "none.pdf") == ds.NOT_FOUND
    assert reason(ds.ingest, config, "d.pdf") == ds.NOT_REGULAR_FILE


def test_junctions_and_reparse_points_are_refused(config, tmp_path):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.pdf").write_bytes(pdf())
    _winapi.CreateJunction(str(outside), str(config.inbox / "j.pdf"))

    assert reason(ds.ingest, config, "j.pdf") == ds.REPARSE_POINT
    assert objects(config) == []


def test_symlinks_are_refused(config, tmp_path):
    target = tmp_path / "secret.pdf"
    target.write_bytes(pdf())
    try:
        os.symlink(target, config.inbox / "s.pdf")
    except OSError:
        pytest.skip("symlink creation needs the Windows symlink privilege here")

    assert reason(ds.ingest, config, "s.pdf") == ds.REPARSE_POINT


def test_hard_links_are_refused(config, tmp_path):
    target = tmp_path / "elsewhere.pdf"
    target.write_bytes(pdf())
    os.link(target, config.inbox / "h.pdf")

    assert reason(ds.ingest, config, "h.pdf") == ds.HARD_LINKED


# ---------------------------------------------------------- configuration


def test_storage_root_misconfiguration_is_refused(roots, tmp_path):
    import _winapi

    inbox, store = roots
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / "file").write_text("x")
    _winapi.CreateJunction(str(store), str(tmp_path / "store_link"))
    nested = store / "inbox"
    nested.mkdir()
    cases = [
        (None, str(store)), (str(inbox), None), ("", str(store)), ("relative", str(store)),
        (str(tmp_path / "missing"), str(store)), (str(tmp_path / "file"), str(store)),
        (str(inbox), str(inbox)), (str(nested), str(store)), (str(inbox), str(tmp_path / "store_link")),
        (str(repo / "tests"), str(store)), (str(inbox), str(repo / ".claude" / "runtime")),
        (str(inbox) + " ", str(store)), ("\\\\server\\share", str(store)),
    ]
    for inbox_value, store_value in cases:
        with pytest.raises(ds.DocumentStoreError) as error:
            ds.StoreConfig.validated(inbox_value, store_value, environ={})
        assert error.value.reason == ds.CONFIG_INVALID, (inbox_value, store_value)

    with pytest.raises(ds.DocumentStoreError):              # inside a sync folder
        ds.StoreConfig.validated(str(inbox), str(store), environ={"OneDrive": str(tmp_path)})
    with pytest.raises(ds.DocumentStoreError):              # nothing configured
        ds.StoreConfig.from_env({})


def test_configuration_comes_only_from_the_environment(roots):
    inbox, store = roots
    config = ds.StoreConfig.from_env({ds.INBOX_ENV: str(inbox), ds.STORE_ENV: str(store)})

    assert (config.inbox, config.store) == (inbox, store)
    assert config.staging.is_dir() and (config.objects / ds.HASH_DIR).is_dir()


def test_no_document_store_is_configured_by_default():
    assert ds.INBOX_ENV not in os.environ and ds.STORE_ENV not in os.environ


# ------------------------------------------------------------ content hashing


def test_an_expected_hash_is_a_constraint_never_proof(config):
    data = pdf()
    put(config, "a.pdf", data)
    wrong = hashlib.sha256(b"other").hexdigest()

    assert reason(ds.ingest, config, "a.pdf", expected_sha256=wrong) == ds.CONTENT_MISMATCH
    assert objects(config) == [] and staging(config) == []
    assert ds.ingest(config, "a.pdf", expected_sha256=hashlib.sha256(data).hexdigest()).reused is False


def test_hash_mismatch_between_copy_and_staged_bytes_is_refused(config, monkeypatch):
    put(config, "a.pdf", pdf())
    real = ds._fsync

    def corrupt(fd):
        os.write(fd, b"tampered")                            # staged bytes changed after copy
        real(fd)

    monkeypatch.setattr(ds, "_fsync", corrupt)

    assert reason(ds.ingest, config, "a.pdf") == ds.HASH_MISMATCH
    assert objects(config) == [] and staging(config) == []


def test_duplicate_content_is_stored_once(config):
    data = png()
    put(config, "one.png", data)
    put(config, "two.png", data)

    first, second = ds.ingest(config, "one.png"), ds.ingest(config, "two.png")

    assert first.sha256 == second.sha256 and (first.reused, second.reused) == (False, True)
    assert len(objects(config)) == 1 and staging(config) == []


def test_different_contents_with_the_same_original_name_are_separate_objects(config):
    put(config, "same.pdf", pdf())
    first = ds.ingest(config, "same.pdf")
    os.remove(config.inbox / "same.pdf")
    put(config, "same.pdf", pdf(pad=10))

    second = ds.ingest(config, "same.pdf")

    assert first.sha256 != second.sha256 and len(objects(config)) == 2
    assert ds.verify_object(config, first.sha256) == ds.verify_object(config, second.sha256) == "VERIFIED"


def test_concurrent_ingestion_of_identical_content_is_safe(config):
    data = docx()
    for i in range(8):
        put(config, f"c{i}.docx", data)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def run(i):
        barrier.wait()
        try:
            results.append(ds.ingest(config, f"c{i}.docx"))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len({r.sha256 for r in results}) == 1 and [r.reused for r in results].count(False) == 1
    assert len(objects(config)) == 1 and staging(config) == []


def test_a_transient_sharing_violation_on_a_stored_object_is_retried(config, monkeypatch):
    """Windows briefly refuses handles to a just-renamed file (found by the
    concurrency stress); reuse must wait, not fail."""
    put(config, "a.pdf", pdf())
    stored = ds.ingest(config, "a.pdf")
    real_open, calls = os.open, {"n": 0}

    def busy_twice(file, *args, **kwargs):
        if os.path.normcase(str(file)) == os.path.normcase(str(ds.object_path(config, stored.sha256))):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError("sharing violation")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(ds.os, "open", busy_twice)

    assert ds.ingest(config, "a.pdf").reused is True
    assert ds.verify_object(config, stored.sha256) == "VERIFIED"


def test_a_persistent_permission_error_on_a_stored_object_is_reported(config, monkeypatch):
    put(config, "a.pdf", pdf())
    stored = ds.ingest(config, "a.pdf")
    target = os.path.normcase(str(ds.object_path(config, stored.sha256)))
    real_open = os.open
    monkeypatch.setattr(ds, "SHARING_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(ds.os, "open", lambda file, *a, **k: (_ for _ in ()).throw(
        PermissionError("denied")) if os.path.normcase(str(file)) == target else real_open(file, *a, **k))

    assert reason(ds.verify_object, config, stored.sha256) == ds.PERMISSION_DENIED
    assert reason(ds.ingest, config, "a.pdf") == ds.PERMISSION_DENIED
    assert staging(config) == []


# -------------------------------------------------------------- source races


def test_source_modified_during_copy_is_refused(config, monkeypatch):
    path = put(config, "a.pdf", pdf())
    real = ds._read_chunk
    state = {"done": False}

    def modify_once(fd):
        if not state["done"]:
            state["done"] = True
            time.sleep(0.02)
            with open(path, "r+b") as handle:
                handle.seek(10)
                handle.write(b"X")
        return real(fd)

    monkeypatch.setattr(ds, "_read_chunk", modify_once)

    assert reason(ds.ingest, config, "a.pdf") == ds.SOURCE_CHANGED
    assert objects(config) == [] and staging(config) == []


def test_source_replaced_between_validation_and_open_is_refused(config, monkeypatch):
    path = put(config, "a.pdf", pdf())
    real = ds._resolve_source

    def swap(config_, name):
        resolved = real(config_, name)
        os.remove(path)
        path.write_bytes(pdf(pad=5))                        # a different file object
        return resolved

    monkeypatch.setattr(ds, "_resolve_source", swap)

    assert reason(ds.ingest, config, "a.pdf") == ds.SOURCE_CHANGED
    assert objects(config) == []


# ----------------------------------------------------------- fault injection


def test_failure_before_staging_leaves_nothing(config, monkeypatch):
    put(config, "a.pdf", pdf())
    monkeypatch.setattr(ds, "_resolve_source", lambda *_: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(OSError):
        ds.ingest(config, "a.pdf")
    assert objects(config) == [] and staging(config) == []


def test_partial_staging_copy_is_removed_and_never_promoted(config, monkeypatch):
    put(config, "big.pdf", pdf(pad=3 * ds.CHUNK))
    real = ds._write_all
    calls = {"n": 0}

    def fail_second(fd, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real(fd, data)

    monkeypatch.setattr(ds, "_write_all", fail_second)

    with pytest.raises(OSError):
        ds.ingest(config, "big.pdf")
    assert objects(config) == [] and staging(config) == []


def test_flush_failure_is_refused_without_promotion(config, monkeypatch):
    put(config, "a.pdf", pdf())
    monkeypatch.setattr(ds, "_fsync", lambda fd: (_ for _ in ()).throw(OSError("flush")))

    assert reason(ds.ingest, config, "a.pdf") == ds.FLUSH_FAILED
    assert objects(config) == [] and staging(config) == []


def test_promotion_failure_is_reported_and_cleaned_up(config, monkeypatch):
    put(config, "a.pdf", pdf())
    monkeypatch.setattr(ds, "_promote_no_overwrite",
                        lambda *_: (_ for _ in ()).throw(PermissionError("denied")))

    assert reason(ds.ingest, config, "a.pdf") == ds.PROMOTION_FAILED
    assert objects(config) == [] and staging(config) == []


def test_permission_errors_are_reported(config, monkeypatch):
    path = put(config, "a.pdf", pdf())
    real_open = os.open

    def deny(file, *args, **kwargs):
        if os.path.normcase(str(file)) == os.path.normcase(str(path)):
            raise PermissionError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(ds.os, "open", deny)

    assert reason(ds.ingest, config, "a.pdf") == ds.PERMISSION_DENIED
    assert staging(config) == []


def test_existing_destination_with_other_bytes_is_an_integrity_failure_and_never_overwritten(config):
    data = pdf()
    sha = hashlib.sha256(data).hexdigest()
    destination = ds.object_path(config, sha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"corrupted bytes under the right name")
    put(config, "a.pdf", data)

    assert reason(ds.ingest, config, "a.pdf") == ds.INTEGRITY_FAILURE
    assert destination.read_bytes() == b"corrupted bytes under the right name"   # untouched
    assert staging(config) == []
    assert ds.verify_object(config, sha) == "CORRUPT"


def test_interruption_after_promotion_is_recoverable(config, monkeypatch):
    data = jpeg()
    put(config, "a.jpg", data)
    real = ds._promote_no_overwrite

    def promote_then_die(source, destination):
        real(source, destination)
        raise KeyboardInterrupt("process interrupted after promotion")

    monkeypatch.setattr(ds, "_promote_no_overwrite", promote_then_die)
    with pytest.raises(KeyboardInterrupt):
        ds.ingest(config, "a.jpg")
    monkeypatch.setattr(ds, "_promote_no_overwrite", real)

    sha = hashlib.sha256(data).hexdigest()
    assert staging(config) == []
    assert [e.classification for e in ds.inventory(config)] == [ds.ORPHANED_FINALIZED]
    again = ds.ingest(config, "a.jpg")                       # same bytes: verified reuse
    assert again.reused is True and again.sha256 == sha and len(objects(config)) == 1


def test_stored_objects_are_never_modified(config):
    put(config, "a.png", png())
    stored = ds.ingest(config, "a.png")
    final = ds.object_path(config, stored.sha256)
    before = (final.read_bytes(), os.stat(final).st_mtime_ns)

    ds.ingest(config, "a.png")                               # reuse path
    with pytest.raises(PermissionError):                     # read-only attribute
        with open(final, "ab") as handle:
            handle.write(b"x")

    assert (final.read_bytes(), os.stat(final).st_mtime_ns) == before


# ------------------------------------------------------- inventory and cleanup


def test_inventory_classifies_without_deleting_anything(config):
    put(config, "ref.pdf", pdf())
    put(config, "orphan.png", png())
    put(config, "bad.jpg", jpeg())
    referenced = ds.ingest(config, "ref.pdf")
    orphan = ds.ingest(config, "orphan.png")
    corrupt = ds.ingest(config, "bad.jpg")
    corrupt_path = ds.object_path(config, corrupt.sha256)
    os.chmod(corrupt_path, stat.S_IREAD | stat.S_IWRITE)
    corrupt_path.write_bytes(b"bit rot")
    stale = config.staging / f"{ds.STAGING_PREFIX}dead{ds.STAGING_SUFFIX}"
    stale.write_bytes(b"partial")
    (config.staging / "unrelated.txt").write_text("not ours")
    before = sorted(p for p in config.store.rglob("*") if p.is_file())

    found = {Path(e.path).name: e.classification for e in ds.inventory(config, [referenced.object_id])}

    assert found[referenced.sha256] == ds.VERIFIED_REFERENCED
    assert found[orphan.sha256] == ds.ORPHANED_FINALIZED
    assert found[corrupt.sha256] == ds.CORRUPT_STORED
    assert found[stale.name] == ds.INCOMPLETE_STAGING
    assert found["unrelated.txt"] == ds.UNEXPECTED_ENTRY
    assert sorted(p for p in config.store.rglob("*") if p.is_file()) == before   # nothing deleted


def test_staging_sweep_is_explicit_narrow_and_never_touches_objects(config):
    put(config, "a.pdf", pdf())
    stored = ds.ingest(config, "a.pdf")
    old = config.staging / f"{ds.STAGING_PREFIX}old{ds.STAGING_SUFFIX}"
    fresh = config.staging / f"{ds.STAGING_PREFIX}fresh{ds.STAGING_SUFFIX}"
    other = config.staging / "keep.part"
    for path in (old, fresh, other):
        path.write_bytes(b"x")
    ancient = time.time() - 7200
    os.utime(old, (ancient, ancient))
    os.utime(other, (ancient, ancient))

    with pytest.raises(ds.DocumentStoreError):
        ds.sweep_staging(config, older_than_seconds=1)        # too aggressive
    removed = ds.sweep_staging(config, older_than_seconds=3600)

    assert removed == [old.name]
    assert fresh.exists() and other.exists()
    assert ds.verify_object(config, stored.sha256) == "VERIFIED"


# ------------------------------------------- final review regressions (A1a)


def test_staging_sweep_threshold_cannot_reach_active_operations(config):
    """An ingestion stalled by antivirus or a slow disk is still active: the
    sweep must never accept a threshold an active operation can exceed."""
    for too_short in (60, 600, 3599):
        with pytest.raises(ds.DocumentStoreError) as error:
            ds.sweep_staging(config, older_than_seconds=too_short)
        assert error.value.reason == ds.CONFIG_INVALID
    assert ds.sweep_staging(config, older_than_seconds=3600) == []


def test_a_staging_file_removed_mid_operation_fails_closed(config, monkeypatch):
    put(config, "a.pdf", pdf())
    real = ds.validate_format

    def swept(path, declared):
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        os.remove(path)                                      # an external sweep
        return real

    monkeypatch.setattr(ds, "validate_format", swept)

    with pytest.raises(ds.DocumentStoreError):
        ds.ingest(config, "a.pdf")
    assert objects(config) == [] and staging(config) == []


@pytest.mark.parametrize("which", ["staging", "objects"])
def test_a_store_directory_swapped_for_a_junction_after_validation_is_refused(config, tmp_path, which):
    import _winapi

    put(config, "a.pdf", pdf())
    victim = config.staging if which == "staging" else config.objects / ds.HASH_DIR
    elsewhere = tmp_path / f"elsewhere-{which}"
    elsewhere.mkdir()
    os.rmdir(victim)
    _winapi.CreateJunction(str(elsewhere), str(victim))

    assert reason(ds.ingest, config, "a.pdf") == ds.CONFIG_INVALID
    assert list(elsewhere.rglob("*")) == []                  # nothing written through it


def test_a_stored_object_that_vanishes_is_a_stable_integrity_failure(config, monkeypatch):
    """Antivirus quarantine can remove a just-promoted file; the caller gets a
    deterministic reason, never a raw OSError or a success."""
    put(config, "a.pdf", pdf())
    real = ds._promote_no_overwrite

    def promote_then_quarantine(source, destination):
        real(source, destination)
        os.chmod(destination, stat.S_IREAD | stat.S_IWRITE)
        os.remove(destination)

    monkeypatch.setattr(ds, "_promote_no_overwrite", promote_then_quarantine)

    assert reason(ds.ingest, config, "a.pdf") == ds.INTEGRITY_FAILURE
    assert staging(config) == []


def test_concurrent_ingestion_of_different_content_stays_independent(config):
    payloads = {f"d{i}.pdf": pdf(pad=i + 1) for i in range(8)}
    for name, data in payloads.items():
        put(config, name, data)
    results, errors = {}, []
    barrier = threading.Barrier(len(payloads))

    def run(name):
        barrier.wait()
        try:
            results[name] = ds.ingest(config, name)
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=run, args=(n,)) for n in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    for name, data in payloads.items():
        stored = results[name]
        assert stored.sha256 == hashlib.sha256(data).hexdigest() and stored.reused is False
        assert ds.object_path(config, stored.sha256).read_bytes() == data
    assert len(objects(config)) == len(payloads) and staging(config) == []


# ------------------------------------------------------ integration boundaries


def test_the_store_has_no_database_or_authorization_coupling():
    source = Path(ds.__file__).read_text(encoding="utf-8")

    for forbidden in ("psycopg", "MerchantRepository", "merchant_pending_confirmation",
                      "merchant_direct_handoff", "TEST_MODE_COMMANDS", "document_revisions",
                      "record_pending", "execution_claims", "project_events"):
        assert forbidden not in source, forbidden


def test_runtime_and_document_writes_stay_disabled():
    from claude.hooks import merchant_direct_handoff as handoff

    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    # CP12H.MASTER: metadata-only revisions and decisions run on the test
    # database only as confirmed lifecycle operations; no managed-file write
    # (document_files INSERT) exists and runtime stays disabled.
    assert "document revision-create" in handoff.LIFECYCLE_ONLY_COMMANDS
    assert "document approve" in handoff.LIFECYCLE_ONLY_COMMANDS
    assert not handoff.direct_execute_enabled("document revision-create", "runtime")
