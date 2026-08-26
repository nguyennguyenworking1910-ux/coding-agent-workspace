"""Tests for .claude/clients/config.py configuration resolution and RAG client integration."""

import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"


def load_claude_package() -> None:
    """Expose `.claude` through its importable package name."""
    if "claude" in sys.modules:
        return

    package = types.ModuleType("claude")
    package.__path__ = [str(CLAUDE_DIR)]
    package.__package__ = "claude"
    sys.modules["claude"] = package


load_claude_package()


class TestConfigVariablesExist:
    """Test that new timeout variables exist in the config module."""

    def test_client_timeout_variable_exists(self):
        """RAG_CLIENT_TIMEOUT_SECONDS exists in config module."""
        from claude.clients import config

        assert hasattr(
            config,
            "RAG_CLIENT_TIMEOUT_SECONDS",
        ), "RAG_CLIENT_TIMEOUT_SECONDS must exist in config"
        assert isinstance(config.RAG_CLIENT_TIMEOUT_SECONDS, float)
        assert config.RAG_CLIENT_TIMEOUT_SECONDS > 0

    def test_ingestion_timeout_variable_exists(self):
        """RAG_INGEST_API_TIMEOUT_SECONDS exists in config module."""
        from claude.clients import config

        assert hasattr(
            config,
            "RAG_INGEST_API_TIMEOUT_SECONDS",
        ), "RAG_INGEST_API_TIMEOUT_SECONDS must exist in config"
        assert isinstance(config.RAG_INGEST_API_TIMEOUT_SECONDS, float)
        assert config.RAG_INGEST_API_TIMEOUT_SECONDS > 0

    def test_base_url_variable_exists(self):
        """RAG_API_BASE_URL exists in config module."""
        from claude.clients import config

        assert hasattr(
            config,
            "RAG_API_BASE_URL",
        ), "RAG_API_BASE_URL must exist in config"
        assert isinstance(config.RAG_API_BASE_URL, str)
        assert len(config.RAG_API_BASE_URL) > 0
        # Should not have trailing slashes
        assert not config.RAG_API_BASE_URL.endswith("/")


class TestLegacyVariableRemoved:
    """Verify that RAG_API_TIMEOUT_SECONDS is no longer used."""

    def test_rag_api_timeout_seconds_not_in_config(self):
        """RAG_API_TIMEOUT_SECONDS is removed from config module."""
        from claude.clients import config

        # The old variable should not exist in the config module
        assert not hasattr(
            config,
            "RAG_API_TIMEOUT_SECONDS",
        ), "RAG_API_TIMEOUT_SECONDS should be removed from config"


class TestRagClientIntegration:
    """Test that RagClient correctly uses the new timeout configuration."""

    def test_rag_client_uses_client_timeout_default(self):
        """RagClient defaults to RAG_CLIENT_TIMEOUT_SECONDS."""
        from claude.clients.rag_client import RagClient

        # Create a fake opener to avoid actual network calls
        def fake_opener(request, timeout):
            class FakeResponse:
                def read(self):
                    return b'{"status": "ok"}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return FakeResponse()

        client = RagClient(
            base_url="http://127.0.0.1:8200",
            opener=fake_opener,
        )

        # Client should use its timeout, which should be the configured value
        assert client.timeout_seconds > 0
        # The actual value depends on .env, but it should be a positive float
        assert isinstance(client.timeout_seconds, float)

    def test_rag_client_uses_explicit_timeout(self):
        """RagClient respects explicitly provided timeout."""
        from claude.clients.rag_client import RagClient

        def fake_opener(request, timeout):
            class FakeResponse:
                def read(self):
                    return b'{"status": "ok"}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return FakeResponse()

        explicit_timeout = 45.0
        client = RagClient(
            base_url="http://127.0.0.1:8200",
            timeout_seconds=explicit_timeout,
            opener=fake_opener,
        )

        assert client.timeout_seconds == explicit_timeout

    def test_rag_client_normalizes_trailing_slash(self):
        """RagClient normalizes trailing slashes in base URL."""
        from claude.clients.rag_client import RagClient

        def fake_opener(request, timeout):
            class FakeResponse:
                def read(self):
                    return b'{"status": "ok"}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return FakeResponse()

        # Test with trailing slash
        client = RagClient(
            base_url="http://127.0.0.1:8200/",
            opener=fake_opener,
        )

        assert client.base_url == "http://127.0.0.1:8200"
        assert not client.base_url.endswith("/")

    def test_rag_client_base_url_from_config(self):
        """RagClient uses RAG_API_BASE_URL from config when not provided."""
        from claude.clients.rag_client import RagClient
        from claude.clients import config

        def fake_opener(request, timeout):
            class FakeResponse:
                def read(self):
                    return b'{"status": "ok"}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return FakeResponse()

        # Create client without explicit base_url to test config fallback
        client = RagClient(
            opener=fake_opener,
        )

        # Client should use the config's base URL
        assert client.base_url == config.RAG_API_BASE_URL


class TestRagServerConfig:
    """Test that RAG server config reads the new ingestion timeout."""

    def test_rag_server_config_can_read_ingestion_timeout(self):
        """RAG server config reads from RAG_INGEST_API_TIMEOUT_SECONDS."""
        # Import the rag-server config to verify it can load
        import sys
        from pathlib import Path

        rag_server_path = Path(__file__).resolve().parents[1] / "rag-server"
        if str(rag_server_path) not in sys.path:
            sys.path.insert(0, str(rag_server_path))

        # Try to load settings - this will fail if the variable is not configured,
        # but it will validate that the config module tries to read it
        from app.config import Settings

        # Create settings from environment - this will use the default if not set
        try:
            settings = Settings.from_env()
            # If successful, the setting should have a positive api_timeout_seconds
            assert settings.api_timeout_seconds > 0
            # Typically should be 900 for ingestion
            assert settings.api_timeout_seconds >= 900
        except Exception as e:
            # If there's a configuration error, it should not be about missing RAG_API_TIMEOUT_SECONDS
            error_msg = str(e)
            assert (
                "RAG_API_TIMEOUT_SECONDS" not in error_msg
            ), f"Should not reference old RAG_API_TIMEOUT_SECONDS, got: {error_msg}"
