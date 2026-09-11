#!/usr/bin/env python3
"""Read-only preflight verification for 22-merchant batch activation.

This script performs a comprehensive read-only check before applying
the batch activation of 22 merchants from ONBOARDING to ACTIVE status.

Usage:
    python merchant_activation_preflight.py [--database runtime|test]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from claude.agents.tools.merchant.cli_contract import render_json
    from claude.clients.merchant.repository import MerchantRepository
    from claude.clients.merchant.read_repository import MerchantReadRepository
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from agents.tools.merchant.cli_contract import render_json  # type: ignore
    from clients.merchant.repository import MerchantRepository  # type: ignore
    from clients.merchant.read_repository import (  # type: ignore
        MerchantReadRepository,
    )


EXPECTED_MERCHANT_COUNT = 22
FROM_STATUS = "ONBOARDING"
TARGET_STATUS = "ACTIVE"
BATCH_REASON = "Existing merchants imported during runtime initialization"


def main(argv: list[str] | None = None) -> int:
    """Run preflight verification."""
    parser = argparse.ArgumentParser(
        description="Preflight verification for 22-merchant batch activation"
    )
    parser.add_argument(
        "--database",
        choices=("runtime", "test"),
        default="runtime",
        help="Database target (default: runtime)",
    )

    args = parser.parse_args(argv)

    try:
        result = run_preflight(args.database)
        print(render_json(result))
        return 0
    except Exception as error:
        print(
            render_json(
                {
                    "success": False,
                    "error": {
                        "type": error.__class__.__name__,
                        "message": str(error)[:500],
                    },
                }
            ),
            file=sys.stderr,
        )
        return 1


def run_preflight(database: str) -> dict[str, Any]:
    """Execute preflight checks."""
    repository = MerchantRepository(
        role="app" if database == "runtime" else "test"
    )
    reads = MerchantReadRepository(repository)

    # Read all merchants
    all_merchants = reads.merchant_list(status=None)

    # Filter to ONBOARDING
    onboarding = [
        m for m in all_merchants
        if m.get("account_status") == FROM_STATUS
    ]

    # Sort deterministic by ID
    onboarding_sorted = sorted(
        onboarding,
        key=lambda m: m.get("id", ""),
    )

    # Verify count
    if len(onboarding_sorted) != EXPECTED_MERCHANT_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_MERCHANT_COUNT} merchants in {FROM_STATUS}, "
            f"found {len(onboarding_sorted)}"
        )

    # Build merchant manifest (deterministic ordering, exact state)
    manifest_entries = [
        {
            "merchant_id": str(m.get("id", "")),
            "code": str(m.get("code", "")),
            "account_status": str(m.get("account_status", "")),
            "version": int(m.get("version", 0)),
        }
        for m in onboarding_sorted
    ]

    # Build proposal payload
    payload = {
        "from_status": FROM_STATUS,
        "target_status": TARGET_STATUS,
        "expected_count": len(manifest_entries),
        "reason": BATCH_REASON,
        "manifest": manifest_entries,
    }

    # Calculate payload_hash from complete payload
    payload_canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_hash = hashlib.sha256(payload_canonical).hexdigest()

    # Calculate proposal_hash (same as payload_hash for proposal)
    proposal_hash = payload_hash

    # Calculate confirmation_hash from proposal_hash + manifest
    confirmation_data = {
        "proposal_hash": proposal_hash,
        "manifest_sha256": hashlib.sha256(
            json.dumps(
                manifest_entries,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    }
    confirmation_canonical = json.dumps(
        confirmation_data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    confirmation_hash = hashlib.sha256(confirmation_canonical).hexdigest()

    # Retain merchant_summary for output compatibility
    merchant_summary = manifest_entries

    # Expected event count = one MERCHANT_ACTIVATED event per merchant
    expected_event_count = len(onboarding_sorted)

    preflight_result = {
        "success": True,
        "mode": "PREFLIGHT",
        "database": database,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "batch_info": {
            "from_status": FROM_STATUS,
            "target_status": TARGET_STATUS,
            "reason": BATCH_REASON,
            "expected_count": EXPECTED_MERCHANT_COUNT,
            "actual_count": len(onboarding_sorted),
            "count_matches": len(onboarding_sorted) == EXPECTED_MERCHANT_COUNT,
        },
        "merchants": merchant_summary,
        "hashes": {
            "payload_hash": payload_hash,
            "proposal_hash": proposal_hash,
            "confirmation_hash": confirmation_hash,
        },
        "backup_required": True,
        "backup_instructions": (
            "Create PostgreSQL backup before apply:\n"
            "  Linux/macOS: pg_dump coding_agent_merchant > backup_before_activation_$(date +%s).sql\n"
            "  Windows: pg_dump coding_agent_merchant > backup_before_activation_%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.sql"
        ),
        "expected_mutations": {
            "merchants_updated": EXPECTED_MERCHANT_COUNT,
            "merchant_versions_incremented": EXPECTED_MERCHANT_COUNT,
            "audit_events_created": expected_event_count,
            "event_type": "MERCHANT_ACTIVATED",
        },
        "verification": {
            "all_merchants_onboarding": all(
                m.get("account_status") == FROM_STATUS
                for m in onboarding_sorted
            ),
            "all_ids_valid_uuid": all(
                _is_valid_uuid(m.get("id"))
                for m in onboarding_sorted
            ),
            "all_codes_present": all(
                m.get("code")
                for m in onboarding_sorted
            ),
            "all_versions_positive": all(
                m.get("version", 0) > 0
                for m in onboarding_sorted
            ),
            "deterministic_ordering": (
                [m.get("id") for m in onboarding_sorted]
                == sorted([m.get("id") for m in onboarding_sorted])
            ),
        },
        "next_steps": [
            "1. Review merchant list above",
            "2. Verify hashes match proposal",
            "3. Create backup as instructed",
            "4. Run activation apply with matching confirmation token",
            "5. Verify post-activation state",
        ],
    }

    return preflight_result


def _is_valid_uuid(value: Any) -> bool:
    """Check if value is a valid UUID."""
    try:
        uuid.UUID(str(value))
        return True
    except (AttributeError, ValueError, TypeError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
