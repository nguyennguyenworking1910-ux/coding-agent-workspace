"""Read-only planning for standard runtime template initialization."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from claude.agents.tools.merchant.workflow_templates import (
    standard_template_manifest,
)

from .runtime_readiness import (
    BUSINESS_TABLES,
    TEMPLATE_INITIALIZATION_READY,
    RuntimeReadinessReport,
)


TEMPLATE_PLAN_VERSION = 1
RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 5434
RUNTIME_DATABASE = "coding_agent_merchant"
RUNTIME_READ_ROLE = "merchant_app"
RUNTIME_WRITE_ROLE = "merchant_owner"
TEMPLATE_AUTHORIZATION_PHRASE = "STANDARD_TEMPLATES_AUTHORIZED"
EXPECTED_TEMPLATE_COUNT = 4
EXPECTED_STEP_COUNT = 64
EXPECTED_DEPENDENCY_COUNT = 68
EXPECTED_READINESS_TEMPLATE_SHA256 = (
    "a654fbafc6c119f424d16cbde68238b91"
    "ab787770b8c2889ec0bee8e2dfe987e"
)
EXPECTED_FULL_TEMPLATE_SHA256 = (
    "71e6570aef9eac09b0707d487388059b"
    "c8f26249c1aa4c08c36a99cd6203842f"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RuntimeTemplatePlanError(RuntimeError):
    """A value-safe rejection at the template plan boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeTemplateInitializationPlan:
    """Immutable review evidence for the separate template write."""

    templates: tuple[Mapping[str, Any], ...]
    manifest_sha256: str
    backup_sha256: str
    plan_sha256: str

    @property
    def template_count(self) -> int:
        return len(self.templates)

    @property
    def step_count(self) -> int:
        return sum(int(item["step_count"]) for item in self.templates)

    @property
    def dependency_count(self) -> int:
        return sum(
            int(item["dependency_count"])
            for item in self.templates
        )

    def safe_summary(self) -> dict[str, Any]:
        return {
            "success": True,
            "plan_version": TEMPLATE_PLAN_VERSION,
            "target": {
                "host": RUNTIME_HOST,
                "port": RUNTIME_PORT,
                "database": RUNTIME_DATABASE,
                "read_role": RUNTIME_READ_ROLE,
                "write_role": RUNTIME_WRITE_ROLE,
            },
            "template_count": self.template_count,
            "step_count": self.step_count,
            "dependency_count": self.dependency_count,
            "templates": [dict(item) for item in self.templates],
            "manifest_sha256": self.manifest_sha256,
            "backup_sha256": self.backup_sha256,
            "plan_sha256": self.plan_sha256,
            "requires_authorization": True,
            "authorization_phrase": TEMPLATE_AUTHORIZATION_PHRASE,
            "execution_contract": {
                "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
                "idempotency": "IDENTICAL_ONLY",
                "conflict_behavior": "FAIL_CLOSED",
                "catalog_changes": 0,
                "business_record_changes": 0,
            },
        }

    def __repr__(self) -> str:
        return (
            "RuntimeTemplateInitializationPlan("
            f"template_count={self.template_count}, "
            f"step_count={self.step_count}, "
            f"dependency_count={self.dependency_count}, "
            f"manifest_sha256={self.manifest_sha256!r}, "
            f"backup_sha256={self.backup_sha256!r}, "
            f"plan_sha256={self.plan_sha256!r})"
        )


def build_runtime_template_initialization_plan(
    readiness: RuntimeReadinessReport,
    *,
    expected_backup_sha256: str,
) -> RuntimeTemplateInitializationPlan:
    """Bind the four built-in templates to exact live readiness."""

    backup_hash = _reviewed_hash(expected_backup_sha256)
    _validate_readiness(readiness, backup_hash)

    manifest = tuple(
        _normalized_manifest_record(record)
        for record in standard_template_manifest()
    )
    manifest_hash = _manifest_hash(manifest)

    if (
        len(manifest) != EXPECTED_TEMPLATE_COUNT
        or sum(int(item["step_count"]) for item in manifest)
        != EXPECTED_STEP_COUNT
        or sum(
            int(item["dependency_count"])
            for item in manifest
        )
        != EXPECTED_DEPENDENCY_COUNT
        or manifest_hash != EXPECTED_FULL_TEMPLATE_SHA256
    ):
        raise RuntimeTemplatePlanError(
            "Standard template manifest differs from the reviewed contract",
            reason_code="TEMPLATE_MANIFEST_MISMATCH",
        )

    plan_hash = _plan_hash(
        manifest=manifest,
        manifest_sha256=manifest_hash,
        backup_sha256=backup_hash,
    )
    return RuntimeTemplateInitializationPlan(
        templates=manifest,
        manifest_sha256=manifest_hash,
        backup_sha256=backup_hash,
        plan_sha256=plan_hash,
    )


def _validate_readiness(
    readiness: Any,
    backup_sha256: str,
) -> None:
    if not isinstance(readiness, RuntimeReadinessReport):
        raise RuntimeTemplatePlanError(
            "Template planning requires validated runtime readiness",
            reason_code="INVALID_READINESS_REPORT",
        )

    exact = (
        readiness.success is True
        and readiness.state == TEMPLATE_INITIALIZATION_READY
        and readiness.database == RUNTIME_DATABASE
        and readiness.user == RUNTIME_READ_ROLE
        and readiness.encoding == "UTF8"
        and readiness.read_only == "on"
        and readiness.schema_owner == RUNTIME_WRITE_ROLE
        and readiness.applied_versions == (1, 2, 3)
        and readiness.pending_versions == ()
        and readiness.stored_template_count == 0
        and readiness.expected_template_sha256
        == EXPECTED_READINESS_TEMPLATE_SHA256
        and set(readiness.business_counts) == set(BUSINESS_TABLES)
        and all(
            count == 0
            for count in readiness.business_counts.values()
        )
        and readiness.backup.ready is True
        and readiness.backup.backup_sha256 == backup_sha256
    )

    if not exact:
        raise RuntimeTemplatePlanError(
            "Runtime state is not exact for template initialization",
            reason_code="READINESS_STATE_MISMATCH",
        )


def _normalized_manifest_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise RuntimeTemplatePlanError(
            "Standard template manifest entry is invalid",
            reason_code="INVALID_TEMPLATE_MANIFEST",
        )

    required = {
        "name",
        "variant",
        "version",
        "project_type",
        "template_id",
        "fingerprint",
        "step_count",
        "dependency_count",
    }

    if set(record) != required:
        raise RuntimeTemplatePlanError(
            "Standard template manifest fields are invalid",
            reason_code="INVALID_TEMPLATE_MANIFEST_FIELDS",
        )

    normalized = {
        "name": record["name"],
        "variant": record["variant"],
        "version": record["version"],
        "project_type": record["project_type"],
        "template_id": record["template_id"],
        "fingerprint": record["fingerprint"],
        "step_count": record["step_count"],
        "dependency_count": record["dependency_count"],
    }

    if any(
        not isinstance(normalized[field], str)
        or not normalized[field]
        for field in (
            "name",
            "variant",
            "project_type",
            "template_id",
        )
    ):
        raise RuntimeTemplatePlanError(
            "Standard template manifest text is invalid",
            reason_code="INVALID_TEMPLATE_MANIFEST_TEXT",
        )

    if (
        not isinstance(normalized["fingerprint"], str)
        or SHA256_PATTERN.fullmatch(
            normalized["fingerprint"]
        )
        is None
    ):
        raise RuntimeTemplatePlanError(
            "Standard template fingerprint is invalid",
            reason_code="INVALID_TEMPLATE_FINGERPRINT",
        )

    for field in ("version", "step_count", "dependency_count"):
        value = normalized[field]

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise RuntimeTemplatePlanError(
                "Standard template numeric metadata is invalid",
                reason_code="INVALID_TEMPLATE_NUMERIC_METADATA",
            )

    return normalized


def _reviewed_hash(value: Any) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeTemplatePlanError(
            "Reviewed backup hash must be a lowercase SHA-256",
            reason_code="INVALID_BACKUP_HASH",
        )

    return value


def _manifest_hash(
    manifest: Sequence[Mapping[str, Any]],
) -> str:
    encoded = json.dumps(
        list(manifest),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan_hash(
    *,
    manifest: Sequence[Mapping[str, Any]],
    manifest_sha256: str,
    backup_sha256: str,
) -> str:
    document = {
        "plan_version": TEMPLATE_PLAN_VERSION,
        "target": {
            "host": RUNTIME_HOST,
            "port": RUNTIME_PORT,
            "database": RUNTIME_DATABASE,
            "read_role": RUNTIME_READ_ROLE,
            "write_role": RUNTIME_WRITE_ROLE,
        },
        "templates": list(manifest),
        "manifest_sha256": manifest_sha256,
        "backup_sha256": backup_sha256,
        "execution_contract": {
            "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
            "idempotency": "IDENTICAL_ONLY",
            "conflict_behavior": "FAIL_CLOSED",
            "catalog_changes": 0,
            "business_record_changes": 0,
        },
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
