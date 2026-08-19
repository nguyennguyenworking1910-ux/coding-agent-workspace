"""Secret redaction for Claude Code transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    """Result of redaction operation."""

    redacted_text: str
    redaction_count: int


REDACTION_VERSION = "1.0.0"


class ChatRedactor:
    """Redacts secrets from chat transcripts."""

    # API key patterns
    ANTHROPIC_API_KEY = re.compile(
        r"sk-ant-[a-zA-Z0-9_\-]{20,}"
    )
    GITHUB_TOKEN = re.compile(
        r"gh[pousr]_[a-zA-Z0-9_]{36,}|gh_[a-zA-Z0-9]{36,}"
    )
    GOOGLE_API_KEY = re.compile(
        r"AIza[0-9A-Za-z\-_]{34,}"
    )
    AWS_ACCESS_KEY = re.compile(
        r"AKIA[0-9A-Z]{16}"
    )

    # Bearer token pattern
    BEARER_TOKEN = re.compile(
        r"[Bb]earer\s+[a-zA-Z0-9\-_.~+/]+={0,2}(?=\s|$)"
    )

    # Private key blocks
    PRIVATE_KEY = re.compile(
        r"-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY[^-]*-----[^-]*-----END\s+(?:RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY-----",
        re.MULTILINE | re.DOTALL,
    )

    # Environment variable assignments with secrets
    # e.g., ANTHROPIC_API_KEY=sk-ant-...
    ENV_SECRET_ASSIGN = re.compile(
        r"([A-Z_]*(?:KEY|TOKEN|PASSWORD|PASSWD|SECRET|CREDENTIAL)[A-Z_]*)=([^\s\n]+)",
        re.IGNORECASE,
    )

    # Authorization header
    AUTHORIZATION_HEADER = re.compile(
        r"[Aa]uthorization:\s*(?:[Bb]earer\s+)?([a-zA-Z0-9\-_.~+/]+={0,2})(?=\s|$|[\n\r])"
    )

    @staticmethod
    def redact(text: str) -> RedactionResult:
        """Redact secrets from text."""
        redacted = text
        count = 0

        patterns = [
            (ChatRedactor.ANTHROPIC_API_KEY, "[REDACTED:ANTHROPIC_API_KEY]"),
            (ChatRedactor.GITHUB_TOKEN, "[REDACTED:GITHUB_TOKEN]"),
            (ChatRedactor.GOOGLE_API_KEY, "[REDACTED:GOOGLE_API_KEY]"),
            (ChatRedactor.AWS_ACCESS_KEY, "[REDACTED:AWS_ACCESS_KEY]"),
            (ChatRedactor.BEARER_TOKEN, "[REDACTED:BEARER_TOKEN]"),
            (ChatRedactor.PRIVATE_KEY, "[REDACTED:PRIVATE_KEY]"),
        ]

        for pattern, replacement in patterns:
            def replace_fn(match):
                nonlocal count
                count += 1
                return replacement
            redacted = pattern.sub(replace_fn, redacted)

        matches = list(ChatRedactor.ENV_SECRET_ASSIGN.finditer(redacted))
        for match in reversed(matches):
            var_name = match.group(1)
            if any(kw in var_name.upper() for kw in ["KEY", "TOKEN", "PASSWORD", "PASSWD", "SECRET", "CREDENTIAL"]):
                redacted = (
                    redacted[:match.start()] +
                    f"{var_name}=[REDACTED:ENV_SECRET]" +
                    redacted[match.end():]
                )
                count += 1

        return RedactionResult(redacted_text=redacted, redaction_count=count)
