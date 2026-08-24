"""Secret redaction for Claude Code transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    """Result of redaction operation."""

    redacted_text: str
    redaction_count: int


REDACTION_VERSION = "2.0.0"


class ChatRedactor:
    """Redacts secrets from chat transcripts."""

    # Anthropic API keys: sk-ant-...
    ANTHROPIC_API_KEY = re.compile(
        r"sk-ant-[a-zA-Z0-9_\-]{20,}"
    )

    # OpenAI API keys: sk-..., sk-proj-..., sk-svcacct-...
    OPENAI_API_KEY = re.compile(
        r"sk-(?:proj-|svcacct-)?[a-zA-Z0-9_\-]{20,}"
    )

    # GitHub tokens: ghp_, gho_, ghu_, ghs_, ghr_, github_pat_
    GITHUB_TOKEN = re.compile(
        r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[a-zA-Z0-9_]{20,}"
    )

    # Google API keys: AIza...
    GOOGLE_API_KEY = re.compile(
        r"AIza[0-9A-Za-z\-_]{30,}"
    )

    # AWS access keys: AKIA...
    AWS_ACCESS_KEY = re.compile(
        r"AKIA[0-9A-Z]{16}"
    )

    # Bearer token pattern (standalone or in headers)
    BEARER_TOKEN = re.compile(
        r"Bearer\s+[a-zA-Z0-9\-_.~+/]+={0,2}(?=\s|$)",
        re.IGNORECASE
    )

    # Authorization headers: Authorization: Bearer/Basic ...
    AUTHORIZATION_HEADER = re.compile(
        r"Authorization:\s*(?:Bearer|Basic)\s+[a-zA-Z0-9\-_.~+/=]+",
        re.IGNORECASE
    )

    # Private key blocks: RSA, EC, OpenSSH, generic PRIVATE KEY
    PRIVATE_KEY = re.compile(
        r"-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH|PGP)?\s*PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA|DSA|EC|OPENSSH|PGP)?\s*PRIVATE\s+KEY-----",
        re.IGNORECASE,
    )

    # Environment variable assignments with secrets
    # Supports: KEY=value, KEY = value, KEY="value", KEY='value'
    ENV_SECRET_ASSIGN = re.compile(
        r"([A-Z_]*(?:KEY|TOKEN|PASSWORD|PASSWD|SECRET|CREDENTIAL)[A-Z_]*)\s*=\s*(?:['\"])?([^\s'\"=\n]+)(?:['\"])?",
        re.IGNORECASE,
    )

    @staticmethod
    def redact(text: str) -> RedactionResult:
        """Redact secrets from text.

        Redaction is idempotent: redacting already-redacted text
        produces the same result as the original redaction.
        """
        redacted = text
        count = 0

        patterns = [
            # Check specific key patterns first before generic ENV_SECRET
            (ChatRedactor.PRIVATE_KEY, "[REDACTED:PRIVATE_KEY]"),
            (ChatRedactor.ANTHROPIC_API_KEY, "[REDACTED:ANTHROPIC_API_KEY]"),
            (ChatRedactor.OPENAI_API_KEY, "[REDACTED:OPENAI_API_KEY]"),
            (ChatRedactor.GITHUB_TOKEN, "[REDACTED:GITHUB_TOKEN]"),
            (ChatRedactor.GOOGLE_API_KEY, "[REDACTED:GOOGLE_API_KEY]"),
            (ChatRedactor.AWS_ACCESS_KEY, "[REDACTED:AWS_ACCESS_KEY]"),
            (ChatRedactor.AUTHORIZATION_HEADER, "[REDACTED:AUTHORIZATION_HEADER]"),
            (ChatRedactor.BEARER_TOKEN, "[REDACTED:BEARER_TOKEN]"),
        ]

        for pattern, replacement in patterns:
            def replace_fn(match):
                nonlocal count
                count += 1
                return replacement
            redacted = pattern.sub(replace_fn, redacted)

        # Environment variable redaction (from the original unredacted text)
        # to avoid matching already-redacted values
        matches = list(ChatRedactor.ENV_SECRET_ASSIGN.finditer(text))
        for match in reversed(matches):
            var_name = match.group(1)
            if any(kw in var_name.upper() for kw in ["KEY", "TOKEN", "PASSWORD", "PASSWD", "SECRET", "CREDENTIAL"]):
                # Find and replace this assignment in the redacted text
                orig_assignment = match.group(0)
                redacted_assignment = f"{var_name}=[REDACTED:ENV_SECRET]"
                redacted = redacted.replace(orig_assignment, redacted_assignment, 1)
                count += 1

        return RedactionResult(redacted_text=redacted, redaction_count=count)
