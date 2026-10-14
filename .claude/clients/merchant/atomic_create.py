"""Atomic, idempotent Merchant creation entry point."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from claude.clients.merchant.execution_ledger import execute_once


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def atomic_create_merchant(
    repository: Any,
    entity_repository: Any,
    *,
    operation_key: str,
    merchant_id: str | None = None,
    code: str,
    name: str,
    region_code: str | None = None,
    created_by: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create and record outcome in one caller-owned transaction."""

    payload = {
        "command": "merchant create",
        "merchant_id": merchant_id,
        "code": code,
        "name": name,
        "region_code": region_code,
        "created_by": created_by,
    }

    payload_hash = _canonical_hash(payload)

    with repository.connection() as connection:
        with connection.transaction():

            def create() -> dict[str, Any]:
                generated_merchant_id = (
                    merchant_id or str(uuid.uuid4())
                )

                result = entity_repository.create_merchant(
                    merchant_id=generated_merchant_id,
                    code=code,
                    name=name,
                    region_code=region_code,
                    created_by=created_by,
                    connection=connection,
                )

                if is_dataclass(result) and not isinstance(
                    result, type
                ):
                    normalized = asdict(result)
                elif isinstance(result, dict):
                    normalized = dict(result)
                elif callable(getattr(result, "to_dict", None)):
                    normalized = result.to_dict()
                else:
                    raise TypeError(
                        "Unexpected Merchant creation result type"
                    )

                if not isinstance(normalized, dict):
                    raise TypeError(
                        "Merchant creation result must be a dictionary"
                    )

                if (
                    normalized.get("merchant_id")
                    != generated_merchant_id
                ):
                    raise ValueError(
                        "Merchant creation returned an unexpected ID"
                    )

                if normalized.get("success") is False:
                    raise ValueError(
                        "Merchant creation returned failure"
                    )

                return {
                    **normalized,
                    "success": True,
                }

            return execute_once(
                connection,
                operation_key=operation_key,
                payload_hash=payload_hash,
                execute=create,
            )
