"""Read-only verification of committed Merchant create evidence."""

from __future__ import annotations

import re
import uuid
from typing import Any


_HASH = re.compile(r"^[0-9a-f]{64}$")


def verify_committed_merchant_create(
    repository: Any,
    *,
    operation_key: str,
    payload_hash: str,
) -> dict[str, Any] | None:
    """
    Return verified committed evidence, or None.

    operation_key and payload_hash must originate from trusted,
    persisted orchestration state, not agent output.
    """

    if (
        not isinstance(operation_key, str)
        or not operation_key.strip()
        or not isinstance(payload_hash, str)
        or not _HASH.fullmatch(payload_hash)
    ):
        return None

    with repository.connection(read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT payload_hash, result
                FROM merchant_ops.merchant_execution_ledger
                WHERE operation_key = %s
                """,
                (operation_key,),
            )

            ledger = cur.fetchone()

            if not isinstance(ledger, dict):
                return None

            if str(ledger.get("payload_hash")) != payload_hash:
                return None

            result = ledger.get("result")

            if not isinstance(result, dict):
                return None

            if result.get("success") is not True:
                return None

            merchant_id = result.get("merchant_id")

            try:
                merchant_uuid = uuid.UUID(merchant_id)
            except (ValueError, TypeError, AttributeError):
                return None

            if str(merchant_uuid) != merchant_id:
                return None

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.merchants
                WHERE id = %s
                """,
                (merchant_uuid,),
            )

            merchant_row = cur.fetchone()

            if (
                not isinstance(merchant_row, dict)
                or merchant_row.get("n") != 1
            ):
                return None

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.project_events
                WHERE merchant_id = %s
                  AND entity_type = 'MERCHANT'
                  AND entity_id = %s
                """,
                (merchant_uuid, merchant_uuid),
            )

            event_row = cur.fetchone()

            if (
                not isinstance(event_row, dict)
                or event_row.get("n") != 1
            ):
                return None

    return {
        "verified": True,
        "operation_key": operation_key,
        "payload_hash": payload_hash,
        "merchant_id": merchant_id,
        "source": "postgresql",
    }
