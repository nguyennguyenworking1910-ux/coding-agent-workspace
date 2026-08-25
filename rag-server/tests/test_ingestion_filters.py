"""Tests for RAG ingestion file filters."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from app.ingestion.filters import FileFilter


class TestSecretFileExclusion:
    """Test that secret files are properly excluded."""

    def test_env_file_rejected(self) -> None:
        """Test that .env file is rejected."""
        path = Path("/repo/.env")
        assert FileFilter.is_secret_file(path) is True

    def test_env_prod_rejected(self) -> None:
        """Test that .env.prod is rejected."""
        path = Path("/repo/.env.prod")
        assert FileFilter.is_secret_file(path) is True

    def test_env_example_allowed(self) -> None:
        """Test that the unified .env.example is allowed."""
        path = Path("/repo/.env.example")
        assert FileFilter.is_secret_file(path) is False

    def test_other_env_example_rejected(self) -> None:
        """Test that only the canonical root template is allowed."""
        path = Path("/repo/.env.custom.example")
        assert FileFilter.is_secret_file(path) is True

    def test_credentials_json_rejected(self) -> None:
        """Test that credentials.json is rejected."""
        path = Path("/repo/credentials.json")
        assert FileFilter.is_secret_file(path) is True

    def test_pem_file_rejected(self) -> None:
        """Test that .pem files are rejected."""
        path = Path("/repo/cert.pem")
        assert FileFilter.is_secret_file(path) is True

    def test_key_file_rejected(self) -> None:
        """Test that .key files are rejected."""
        path = Path("/repo/private.key")
        assert FileFilter.is_secret_file(path) is True

    def test_id_rsa_rejected(self) -> None:
        """Test that id_rsa is rejected."""
        path = Path("/repo/.ssh/id_rsa")
        assert FileFilter.is_secret_file(path) is True

    def test_service_account_json_rejected(self) -> None:
        """Test that service-account*.json files are rejected."""
        path = Path("/repo/service-account-key.json")
        assert FileFilter.is_secret_file(path) is True

    def test_secrets_directory_rejected(self) -> None:
        """Test that any file in secrets directory is rejected."""
        path = Path("/repo/secrets/api_key.txt")
        assert FileFilter.is_secret_file(path) is True

    def test_nested_secrets_directory_rejected(self) -> None:
        """Test that deeply nested secrets directory files are rejected."""
        path = Path("/repo/data/secrets/token.json")
        assert FileFilter.is_secret_file(path) is True


class TestDirectoryExclusion:
    """Test directory exclusion rules."""

    def test_git_directory_excluded(self) -> None:
        """Test that .git directory is excluded."""
        path = Path("/repo/.git/config")
        assert FileFilter.is_excluded_dir(path) is True

    def test_venv_directory_excluded(self) -> None:
        """Test that venv directory is excluded."""
        path = Path("/repo/venv/lib/python.py")
        assert FileFilter.is_excluded_dir(path) is True

    def test_virtualenv_directory_excluded(self) -> None:
        """Test that .venv directory is excluded."""
        path = Path("/repo/.venv/lib/file.py")
        assert FileFilter.is_excluded_dir(path) is True

    def test_node_modules_excluded(self) -> None:
        """Test that node_modules is excluded."""
        path = Path("/repo/node_modules/package/index.js")
        assert FileFilter.is_excluded_dir(path) is True

    def test_pycache_excluded(self) -> None:
        """Test that __pycache__ is excluded."""
        path = Path("/repo/__pycache__/module.pyc")
        assert FileFilter.is_excluded_dir(path) is True

    def test_pytest_cache_excluded(self) -> None:
        """Test that .pytest_cache is excluded."""
        path = Path("/repo/.pytest_cache/.gitignore")
        assert FileFilter.is_excluded_dir(path) is True

    def test_mypy_cache_excluded(self) -> None:
        """Test that .mypy_cache is excluded."""
        path = Path("/repo/.mypy_cache/index.json")
        assert FileFilter.is_excluded_dir(path) is True

    def test_ruff_cache_excluded(self) -> None:
        """Test that .ruff_cache is excluded."""
        path = Path("/repo/.ruff_cache/cache.bin")
        assert FileFilter.is_excluded_dir(path) is True

    def test_model_cache_excluded(self) -> None:
        """Test that .model-cache is excluded."""
        path = Path("/repo/.model-cache/model.bin")
        assert FileFilter.is_excluded_dir(path) is True

    def test_dist_excluded(self) -> None:
        """Test that dist directory is excluded."""
        path = Path("/repo/dist/package.tar.gz")
        assert FileFilter.is_excluded_dir(path) is True

    def test_build_excluded(self) -> None:
        """Test that build directory is excluded."""
        path = Path("/repo/build/lib/module.so")
        assert FileFilter.is_excluded_dir(path) is True

    def test_claude_agent_workspace_excluded(self) -> None:
        """Test that .agent-workspace is excluded."""
        path = Path("/repo/.agent-workspace/state.json")
        assert FileFilter.is_excluded_dir(path) is True

    def test_claude_agent_memory_excluded(self) -> None:
        """Test that .claude/agent-memory-local is excluded."""
        path = Path("/repo/.claude/agent-memory-local/memory.md")
        assert FileFilter.is_excluded_dir(path) is True


class TestFileSizeLimit:
    """Test file size limit enforcement."""

    def test_file_under_limit(self, tmp_path: Path) -> None:
        """Test that file under 2 MiB limit is allowed."""
        file_path = tmp_path / "small.txt"
        file_path.write_text("small content")

        result = FileFilter.filter_path(file_path, tmp_path)
        assert result.allowed is True

    def test_file_over_limit(self, tmp_path: Path) -> None:
        """Test that file over 2 MiB limit is rejected."""
        file_path = tmp_path / "large.bin"
        # Write 2.1 MiB of data
        file_path.write_bytes(b"x" * (2097152 + 100000))

        result = FileFilter.filter_path(file_path, tmp_path)
        assert result.allowed is False
        assert result.reason == "file_too_large"


class TestBinaryFileRejection:
    """Test binary file detection and rejection."""

    def test_text_file_allowed(self) -> None:
        """Test that text content passes binary check."""
        assert FileFilter.is_binary(b"Hello, world!") is False

    def test_utf8_text_allowed(self) -> None:
        """Test that UTF-8 text passes binary check."""
        assert FileFilter.is_binary("Hello, 世界".encode("utf-8")) is False

    def test_nul_byte_detected(self) -> None:
        """Test that NUL bytes are detected as binary."""
        assert FileFilter.is_binary(b"text\x00binary") is True

    def test_pure_binary_detected(self) -> None:
        """Test that binary content with NUL bytes is detected."""
        # NUL byte is a reliable indicator of binary content
        assert FileFilter.is_binary(b"\x89\x00PNG\r\n\x1a\n") is True


class TestFileOutsideRootRejection:
    """Test that files outside repository root are rejected."""

    def test_file_outside_root(self, tmp_path: Path) -> None:
        """Test that file outside root is rejected."""
        root = tmp_path / "repo"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("content")

        result = FileFilter.filter_path(outside, root)
        assert result.allowed is False
        assert result.reason == "outside_repository"


class TestSymlinkRejection:
    """Test symlink rejection (where supported)."""

    @pytest.mark.skipif(
        not hasattr(__import__("os"), "symlink"),
        reason="symlinks not supported",
    )
    def test_symlink_rejected(self, tmp_path: Path) -> None:
        """Test that symlinks are rejected."""
        target = tmp_path / "target.txt"
        target.write_text("content")
        symlink = tmp_path / "link.txt"

        try:
            symlink.symlink_to(target)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        result = FileFilter.filter_path(symlink, tmp_path)
        assert result.allowed is False
        assert result.reason == "symlink"


class TestSourceTypeClassification:
    """Test source type classification."""

    def test_markdown_is_document(self) -> None:
        """Test that .md files are classified as project_document."""
        path = Path("/repo/README.md")
        assert FileFilter.get_source_type(path) == "project_document"

    def test_mdx_is_document(self) -> None:
        """Test that .mdx files are classified as project_document."""
        path = Path("/repo/page.mdx")
        assert FileFilter.get_source_type(path) == "project_document"

    def test_txt_is_document(self) -> None:
        """Test that .txt files are classified as project_document."""
        path = Path("/repo/notes.txt")
        assert FileFilter.get_source_type(path) == "project_document"

    def test_rst_is_document(self) -> None:
        """Test that .rst files are classified as project_document."""
        path = Path("/repo/index.rst")
        assert FileFilter.get_source_type(path) == "project_document"

    def test_python_is_code(self) -> None:
        """Test that .py files are classified as source_code."""
        path = Path("/repo/main.py")
        assert FileFilter.get_source_type(path) == "source_code"

    def test_json_is_code(self) -> None:
        """Test that .json files are classified as source_code."""
        path = Path("/repo/config.json")
        assert FileFilter.get_source_type(path) == "source_code"

    def test_sql_is_code(self) -> None:
        """Test that .sql files are classified as source_code."""
        path = Path("/repo/schema.sql")
        assert FileFilter.get_source_type(path) == "source_code"


class TestSupportedFileExtensions:
    """Test that only supported extensions are allowed."""

    @pytest.mark.parametrize(
        "filename",
        [
            "README.md",
            "guide.mdx",
            "notes.txt",
            "docs.rst",
            "main.py",
            "script.js",
            "module.jsx",
            "helper.mjs",
            "file.cjs",
            "types.ts",
            "component.tsx",
            "config.json",
            "settings.yaml",
            "data.yml",
            "config.toml",
            "schema.sql",
            "deploy.sh",
            "build.ps1",
            "run.bat",
            "Dockerfile",
            "Makefile",
        ],
    )
    def test_supported_extensions(self, filename: str) -> None:
        """Test that supported extensions are recognized."""
        path = Path(f"/repo/{filename}")
        assert FileFilter.is_supported_file(path) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "file.exe",
            "image.png",
            "document.pdf",
            "archive.zip",
            "file.bin",
        ],
    )
    def test_unsupported_extensions(self, filename: str) -> None:
        """Test that unsupported extensions are rejected."""
        path = Path(f"/repo/{filename}")
        assert FileFilter.is_supported_file(path) is False


class TestDirectoryRejection:
    """Test that directories are rejected."""

    def test_directory_rejected(self, tmp_path: Path) -> None:
        """Test that directories are rejected."""
        dir_path = tmp_path / "subdir"
        dir_path.mkdir()

        result = FileFilter.filter_path(dir_path, tmp_path)
        assert result.allowed is False
        assert result.reason == "directory"
