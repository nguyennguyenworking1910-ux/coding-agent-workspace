"""Retention sweep for test-data execution claims (test database only).

Policy:

- ``merchant-direct:`` and ``merchant-scope:`` claims are operational
  execution evidence. A COMPLETED claim records a commit and refuses replay
  of its key; a REVOKED claim is a fence that keeps a stopped attempt from
  ever committing. They are retained and never swept here.
- ACTIVE claims never persist outside an open transaction; never swept.
- ``pytest:`` claims are test data. Tests delete their own rows; this sweep
  removes COMPLETED or REVOKED ``pytest:`` rows older than the cutoff that
  a failed test left behind.

Dry run by default. ``--apply`` deletes in one transaction after the
effective database and user are verified as the test database.

    python -m claude.clients.merchant.claim_retention [--older-than-days N] [--apply]
"""

from __future__ import annotations

import argparse
import sys

from claude.clients.merchant.repository import MerchantRepository


TEST_KEY_PREFIX = "pytest:"
TEST_DATABASE = ("coding_agent_merchant_test", "merchant_test")

_PREDICATE = """
    WHERE starts_with(operation_key, %s)
      AND claim_status IN ('COMPLETED', 'REVOKED')
      AND updated_at < NOW() - make_interval(days => %s)
"""


def sweep_test_claims(
    repository: MerchantRepository,
    *,
    older_than_days: int,
    apply: bool,
) -> list[dict]:
    """Return the swept (or, in a dry run, sweepable) test-data claims."""

    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")

    with repository.connection(read_only=not apply) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                identity = tuple(cursor.fetchone().values())

                if identity != TEST_DATABASE:
                    raise PermissionError(
                        "Claim retention runs on the test database only"
                    )

                # One statement: the rows reported are exactly those removed.
                cursor.execute(
                    (
                        "DELETE FROM merchant_ops.merchant_execution_claims"
                        if apply
                        else "SELECT operation_key, claim_status, updated_at "
                        "FROM merchant_ops.merchant_execution_claims"
                    )
                    + _PREDICATE
                    + (
                        " RETURNING operation_key, claim_status, updated_at"
                        if apply
                        else ""
                    ),
                    (TEST_KEY_PREFIX, older_than_days),
                )
                rows = [dict(row) for row in cursor.fetchall()]

    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--older-than-days", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    rows = sweep_test_claims(
        MerchantRepository(role="test"),
        older_than_days=args.older_than_days,
        apply=args.apply,
    )
    action = "deleted" if args.apply else "would delete"
    print(f"{action} {len(rows)} test-data claim(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
