"""Tests for chat transcript redaction."""

from __future__ import annotations

import pytest

from app.ingestion.chat_redaction import ChatRedactor, REDACTION_VERSION


class TestAnthropicApiKeyRedaction:
    """Test Anthropic API key redaction."""

    def test_anthropic_api_key_redacted(self) -> None:
        """Test Anthropic API key redaction."""
        text = "My API key is sk-ant-abc123def456ghi789jkl012mno345"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ANTHROPIC_API_KEY]" in result.redacted_text
        assert "sk-ant-" not in result.redacted_text
        assert result.redaction_count == 1


class TestOpenAiApiKeyRedaction:
    """Test OpenAI API key redaction."""

    def test_openai_sk_token_redacted(self) -> None:
        """Test OpenAI sk- token redaction."""
        text = "API key: sk-abcdefghij1234567890klmnop"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:OPENAI_API_KEY]" in result.redacted_text
        assert "sk-abcdefghij" not in result.redacted_text
        assert result.redaction_count >= 1

    def test_openai_sk_proj_token_redacted(self) -> None:
        """Test OpenAI sk-proj- token redaction."""
        text = "Project key: sk-proj-abcdefghij1234567890klmnop"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:OPENAI_API_KEY]" in result.redacted_text
        assert "sk-proj-" not in result.redacted_text
        assert result.redaction_count >= 1

    def test_openai_sk_svcacct_token_redacted(self) -> None:
        """Test OpenAI sk-svcacct- token redaction."""
        text = "Service account: sk-svcacct-abcdefghij1234567890"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:OPENAI_API_KEY]" in result.redacted_text
        assert "sk-svcacct-" not in result.redacted_text


class TestGitHubTokenRedaction:
    """Test GitHub token redaction."""

    def test_github_ghp_token_redacted(self) -> None:
        """Test GitHub ghp_ token redaction."""
        text = "Token: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GITHUB_TOKEN]" in result.redacted_text
        assert "ghp_" not in result.redacted_text

    def test_github_gho_token_redacted(self) -> None:
        """Test GitHub gho_ token redaction."""
        text = "Token: gho_abcdefghijklmnopqrstuvwxyz0123456789"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GITHUB_TOKEN]" in result.redacted_text
        assert "gho_" not in result.redacted_text

    def test_github_ghu_token_redacted(self) -> None:
        """Test GitHub ghu_ token redaction."""
        text = "Token: ghu_abcdefghijklmnopqrstuvwxyz0123456789"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GITHUB_TOKEN]" in result.redacted_text
        assert "ghu_" not in result.redacted_text

    def test_github_ghs_token_redacted(self) -> None:
        """Test GitHub ghs_ token redaction."""
        text = "Token: ghs_abcdefghijklmnopqrstuvwxyz0123456789"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GITHUB_TOKEN]" in result.redacted_text
        assert "ghs_" not in result.redacted_text

    def test_github_ghr_token_redacted(self) -> None:
        """Test GitHub ghr_ token redaction."""
        text = "Token: ghr_abcdefghijklmnopqrstuvwxyz0123456789"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GITHUB_TOKEN]" in result.redacted_text
        assert "ghr_" not in result.redacted_text

    def test_github_pat_token_redacted(self) -> None:
        """Test GitHub github_pat_ token redaction."""
        text = "Token: github_pat_abcdefghijklmnopqrstuvwxyz0123456"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GITHUB_TOKEN]" in result.redacted_text
        assert "github_pat_" not in result.redacted_text


class TestGoogleApiKeyRedaction:
    """Test Google API key redaction."""

    def test_google_api_key_redacted(self) -> None:
        """Test Google API key redaction."""
        text = "Google key: AIza123456789012345678901234567890"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:GOOGLE_API_KEY]" in result.redacted_text
        assert "AIza" not in result.redacted_text


class TestAwsAccessKeyRedaction:
    """Test AWS access key redaction."""

    def test_aws_access_key_redacted(self) -> None:
        """Test AWS access key redaction."""
        text = "AKIAIOSFODNN7EXAMPLE"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:AWS_ACCESS_KEY]" in result.redacted_text
        assert "AKIA" not in result.redacted_text


class TestAuthorizationHeaderRedaction:
    """Test authorization header redaction."""

    def test_authorization_bearer_redacted(self) -> None:
        """Test Authorization: Bearer redaction."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:AUTHORIZATION_HEADER]" in result.redacted_text
        assert "Bearer" not in result.redacted_text
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.redacted_text

    def test_authorization_basic_redacted(self) -> None:
        """Test Authorization: Basic redaction."""
        text = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ="
        result = ChatRedactor.redact(text)

        assert "[REDACTED:AUTHORIZATION_HEADER]" in result.redacted_text
        assert "Basic" not in result.redacted_text
        assert "dXNlcm5hbWU6cGFzc3dvcmQ=" not in result.redacted_text

    def test_authorization_case_insensitive(self) -> None:
        """Test case-insensitive authorization header."""
        text = "authorization: bearer abc123def456"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:AUTHORIZATION_HEADER]" in result.redacted_text
        assert "bearer" not in result.redacted_text.lower()


class TestPrivateKeyRedaction:
    """Test private key redaction."""

    def test_rsa_private_key_redacted(self) -> None:
        """Test RSA private key redaction."""
        text = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA2Z3jJXZ4YN7Z...
-----END RSA PRIVATE KEY-----"""
        result = ChatRedactor.redact(text)

        assert "[REDACTED:PRIVATE_KEY]" in result.redacted_text
        assert "BEGIN RSA PRIVATE KEY" not in result.redacted_text

    def test_ec_private_key_redacted(self) -> None:
        """Test EC private key redaction."""
        text = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIIGlVXpzz9...
-----END EC PRIVATE KEY-----"""
        result = ChatRedactor.redact(text)

        assert "[REDACTED:PRIVATE_KEY]" in result.redacted_text

    def test_openssh_private_key_redacted(self) -> None:
        """Test OpenSSH private key redaction."""
        text = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmU...
-----END OPENSSH PRIVATE KEY-----"""
        result = ChatRedactor.redact(text)

        assert "[REDACTED:PRIVATE_KEY]" in result.redacted_text

    def test_private_key_with_hyphens_redacted(self) -> None:
        """Test private key block whose body contains hyphens."""
        text = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQ---
EFBBAHnV9K2---F0QXhCYkLlHM---
-----END PRIVATE KEY-----"""
        result = ChatRedactor.redact(text)

        # Should redact the whole block
        assert "[REDACTED:PRIVATE_KEY]" in result.redacted_text


class TestEnvironmentVariableRedaction:
    """Test environment variable secret redaction."""

    def test_api_key_env_var_simple_redacted(self) -> None:
        """Test API key environment variable redaction."""
        text = "ANTHROPIC_API_KEY=sk-ant-abc123def456"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ENV_SECRET]" in result.redacted_text
        assert "sk-ant-abc123def456" not in result.redacted_text

    def test_env_var_with_spaces_redacted(self) -> None:
        """Test environment assignment with spaces."""
        text = "API_KEY = sk-ant-abc123"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ENV_SECRET]" in result.redacted_text
        assert "sk-ant-" not in result.redacted_text

    def test_env_var_with_quotes_redacted(self) -> None:
        """Test environment assignment with quotes."""
        text = 'API_KEY="sk-ant-abc123def456"'
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ENV_SECRET]" in result.redacted_text
        assert "sk-ant-abc123" not in result.redacted_text

    def test_env_var_with_single_quotes_redacted(self) -> None:
        """Test environment assignment with single quotes."""
        text = "API_KEY='sk-ant-abc123def456'"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ENV_SECRET]" in result.redacted_text
        assert "sk-ant-abc123" not in result.redacted_text

    def test_password_env_var_redacted(self) -> None:
        """Test password environment variable redaction."""
        text = "DATABASE_PASSWORD=super_secret_password_123"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ENV_SECRET]" in result.redacted_text
        assert "super_secret_password_123" not in result.redacted_text

    def test_token_env_var_redacted(self) -> None:
        """Test token environment variable redaction."""
        text = "AUTH_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = ChatRedactor.redact(text)

        assert "[REDACTED:ENV_SECRET]" in result.redacted_text
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.redacted_text


class TestRedactionIdempotency:
    """Test redaction idempotency."""

    def test_double_redaction_is_idempotent(self) -> None:
        """Test that redacting twice produces same result."""
        text = "My key is sk-ant-abc123def456ghi789jkl012mno345"
        result1 = ChatRedactor.redact(text)
        result2 = ChatRedactor.redact(result1.redacted_text)

        # Should be identical
        assert result1.redacted_text == result2.redacted_text
        # Second pass should find no additional secrets
        assert result2.redaction_count == 0

    def test_triple_redaction_idempotent(self) -> None:
        """Test that triple redaction is stable."""
        text = "API_KEY=sk-ant-abc123 TOKEN=ghp_xyz123"
        result1 = ChatRedactor.redact(text)
        result2 = ChatRedactor.redact(result1.redacted_text)
        result3 = ChatRedactor.redact(result2.redacted_text)

        assert result1.redacted_text == result2.redacted_text
        assert result2.redacted_text == result3.redacted_text


class TestRedactionWithoutFalsePositives:
    """Test that redaction doesn't over-match normal code."""

    def test_normal_variable_names_not_redacted(self) -> None:
        """Test that normal variable assignments aren't redacted."""
        text = "user_name=alice\nage=30\nstatus=active"
        result = ChatRedactor.redact(text)

        assert result.redaction_count == 0

    def test_python_code_not_over_redacted(self) -> None:
        """Test that Python code isn't over-redacted."""
        code = """
def authenticate(token):
    response = requests.get(
        "https://api.example.com/auth",
        headers={"Authorization": f"Bearer {token}"}
    )
    return response
"""
        result = ChatRedactor.redact(code)

        # Should redact Bearer token but preserve code structure
        assert "def authenticate" in result.redacted_text

    def test_normal_strings_preserved(self) -> None:
        """Test that normal string content is preserved."""
        text = "The word secret appears in this sentence multiple times for no reason."
        result = ChatRedactor.redact(text)

        # No actual secrets here
        assert "secret" in result.redacted_text
        assert result.redaction_count == 0


class TestMultipleRedactions:
    """Test multiple redactions in one text."""

    def test_multiple_keys_redacted(self) -> None:
        """Test that multiple different keys are all redacted."""
        text = """
API_KEY=sk-ant-abc123
GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
"""
        result = ChatRedactor.redact(text)

        assert result.redaction_count >= 3
        assert "sk-ant-" not in result.redacted_text
        assert "ghp_" not in result.redacted_text
        assert "AKIA" not in result.redacted_text


class TestRedactionVersioning:
    """Test redaction version constant."""

    def test_redaction_version_incremented(self) -> None:
        """Test that redaction version was incremented."""
        assert REDACTION_VERSION == "2.0.0"


class TestRedactionPreservesContent:
    """Test that redaction preserves non-secret content."""

    def test_redaction_preserves_structure(self) -> None:
        """Test that redaction preserves text structure."""
        text = """Step 1: Create API key
Step 2: Set ANTHROPIC_API_KEY=sk-ant-abc123
Step 3: Run the script"""
        result = ChatRedactor.redact(text)

        assert "Step 1:" in result.redacted_text
        assert "Step 2:" in result.redacted_text
        assert "Step 3:" in result.redacted_text
        assert result.redaction_count >= 1

    def test_redaction_log_safety(self) -> None:
        """Test that redacted text is safe to log."""
        text = "Secret key: sk-ant-abc123def456ghi789jklmnop"
        result = ChatRedactor.redact(text)

        # Should be safe to log
        assert "[REDACTED:" in result.redacted_text
        assert "sk-ant-" not in result.redacted_text
        # Can safely print without exposing secret
        log_safe = str(result.redacted_text)
        assert "sk-ant-" not in log_safe
        assert "abc123def456" not in log_safe

    def test_result_contains_no_secrets(self) -> None:
        """Test that result contains no original secret values."""
        secrets = [
            "sk-ant-abcdef123456789012345678901234",
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "AKIAIOSFODNN7EXAMPLE",
        ]
        text = f"secrets: {', '.join(secrets)}"
        result = ChatRedactor.redact(text)

        for secret in secrets:
            assert secret not in result.redacted_text
