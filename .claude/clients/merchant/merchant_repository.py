"""Atomic persistence for Merchant and contact mutations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.merchant_engine import (
    ContactImportPlan,
    MerchantActivationPlan,
    MerchantConflictError,
    MerchantCreationPlan,
    MerchantVersionConflictError,
    propose_contact_import,
    propose_merchant_activation,
    propose_merchant_creation,
)
from claude.clients.merchant.repository import MerchantRepository


class MerchantPersistenceError(RuntimeError):
    """Base error for Merchant entity persistence."""


class MerchantAlreadyExistsError(MerchantPersistenceError):
    """Raised when a Merchant UUID or code already exists."""


class MerchantEntityNotFoundError(MerchantPersistenceError):
    """Raised when a selected Merchant does not exist."""


class MerchantContactConflictError(MerchantPersistenceError):
    """Raised when a contact import conflicts with stored data."""


@dataclass(frozen=True, slots=True)
class MerchantCreationResult:
    """Public result of a committed Merchant creation."""

    merchant_id: str
    code: str
    name: str
    region_code: str | None
    account_status: str
    version: int
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContactImportResult:
    """PII-free result of a committed contact import."""

    merchant_id: str
    contacts_imported: int
    previous_merchant_version: int
    current_merchant_version: int
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MerchantActivationResult:
    """Result of a committed merchant activation."""

    merchant_id: str
    previous_status: str
    current_status: str
    previous_version: int
    current_version: int
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantEntityRepository:
    """Create Merchants and import contacts transactionally."""

    def __init__(self, repository: MerchantRepository) -> None:
        self.repository = repository

    def create_merchant(
        self,
        *,
        merchant_id: str,
        code: str,
        name: str,
        region_code: str | None = None,
        created_by: str | None = None,
    ) -> MerchantCreationResult:
        plan = propose_merchant_creation(
            merchant_id=merchant_id,
            code=code,
            name=name,
            region_code=region_code,
            created_by=created_by,
        )
        event_id = uuid.uuid4()

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        self._insert_merchant(cursor, plan)
                        self._insert_creation_event(
                            cursor,
                            plan,
                            event_id,
                        )
        except errors.UniqueViolation as error:
            raise MerchantAlreadyExistsError(
                "Merchant ID or code already exists"
            ) from error

        return MerchantCreationResult(
            merchant_id=plan.merchant_id,
            code=plan.code,
            name=plan.name,
            region_code=plan.region_code,
            account_status=plan.account_status,
            version=plan.version,
            event_id=str(event_id),
            event_type=plan.event_type,
        )

    def import_contacts(
        self,
        *,
        merchant_id: str,
        contacts: Sequence[Mapping[str, Any]],
        expected_version: int,
        triggered_by: str | None = None,
    ) -> ContactImportResult:
        merchant_uuid = _uuid(merchant_id, "merchant_id")
        event_id = uuid.uuid4()

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        merchant = self._lock_merchant(
                            cursor,
                            merchant_uuid,
                        )
                        plan = propose_contact_import(
                            merchant,
                            contacts=contacts,
                            expected_version=expected_version,
                            triggered_by=triggered_by,
                        )
                        self._insert_contacts(cursor, plan)
                        self._update_merchant_version(
                            cursor,
                            plan,
                        )
                        self._insert_contact_event(
                            cursor,
                            plan,
                            event_id,
                        )
        except errors.UniqueViolation as error:
            raise MerchantContactConflictError(
                "Contact import conflicts with stored data"
            ) from error

        return ContactImportResult(
            merchant_id=plan.merchant_id,
            contacts_imported=len(plan.records),
            previous_merchant_version=(
                plan.expected_version
            ),
            current_merchant_version=(
                plan.new_merchant_version
            ),
            event_id=str(event_id),
            event_type=plan.event_type,
        )

    def activate_merchant(
        self,
        *,
        merchant_id: str,
        expected_version: int,
        reason: str,
        triggered_by: str | None = None,
    ) -> MerchantActivationResult:
        """Activate a merchant transactionally."""

        merchant_uuid = _uuid(merchant_id, "merchant_id")
        event_id = None

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        merchant = self._lock_merchant(
                            cursor,
                            merchant_uuid,
                        )
                        plan = propose_merchant_activation(
                            merchant,
                            expected_version=expected_version,
                            reason=reason,
                            triggered_by=triggered_by,
                        )
                        event_id = uuid.uuid4()
                        self._update_merchant_status(
                            cursor,
                            plan,
                        )
                        self._insert_activation_event(
                            cursor,
                            plan,
                            event_id,
                        )
        except MerchantConflictError as error:
            raise MerchantConflictError(
                str(error)
            ) from error

        return MerchantActivationResult(
            merchant_id=plan.merchant_id,
            previous_status=plan.current_status,
            current_status=plan.target_status,
            previous_version=plan.expected_version,
            current_version=plan.new_merchant_version,
            event_id=str(event_id),
            event_type=plan.event_type,
        )

    def activate_merchants_batch(
        self,
        *,
        from_status: str,
        expected_count: int,
        reason: str,
        triggered_by: str | None = None,
        manifest: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Atomically activate all merchants with exact manifest validation."""

        normalized_from_status = (
            str(from_status).strip().upper()
        )
        normalized_triggered_by = (
            _uuid(triggered_by, "triggered_by")
            if triggered_by is not None
            else None
        )

        if not isinstance(expected_count, int) or expected_count < 1:
            raise MerchantConflictError(
                "expected_count must be a positive integer"
            )

        results: list[MerchantActivationResult] = []

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        merchants = self._read_merchants_by_status_for_update(
                            cursor,
                            normalized_from_status,
                        )

                        if len(merchants) != expected_count:
                            raise MerchantConflictError(
                                f"Expected {expected_count} merchants with "
                                f"status {normalized_from_status}, found "
                                f"{len(merchants)}"
                            )

                        if manifest is not None:
                            self._validate_batch_manifest(
                                merchants,
                                manifest,
                            )

                        for merchant_row in merchants:
                            merchant_id = merchant_row["id"]
                            plan = propose_merchant_activation(
                                merchant_row,
                                expected_version=merchant_row["version"],
                                reason=reason,
                                triggered_by=triggered_by,
                            )
                            event_id = uuid.uuid4()
                            self._update_merchant_status(
                                cursor,
                                plan,
                            )
                            self._insert_activation_event(
                                cursor,
                                plan,
                                event_id,
                            )
                            results.append(
                                MerchantActivationResult(
                                    merchant_id=plan.merchant_id,
                                    previous_status=plan.current_status,
                                    current_status=plan.target_status,
                                    previous_version=plan.expected_version,
                                    current_version=plan.new_merchant_version,
                                    event_id=str(event_id),
                                    event_type=plan.event_type,
                                )
                            )
        except MerchantConflictError as error:
            raise MerchantConflictError(
                str(error)
            ) from error

        return {
            "success": True,
            "mode": "APPLY",
            "command": "merchant activate-all",
            "from_status": normalized_from_status,
            "expected_count": expected_count,
            "activated_count": len(results),
            "results": [result.to_dict() for result in results],
        }

    @staticmethod
    def _read_merchants_by_status(
        cursor: Any,
        status: str,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                id,
                code,
                account_status,
                version
            FROM merchant_ops.merchants
            WHERE account_status = %s
            ORDER BY id ASC
            FOR UPDATE
            """,
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _read_merchants_by_status_for_update(
        cursor: Any,
        status: str,
    ) -> list[dict[str, Any]]:
        """Read merchants by status with explicit FOR UPDATE lock."""
        cursor.execute(
            """
            SELECT
                id,
                code,
                account_status,
                version
            FROM merchant_ops.merchants
            WHERE account_status = %s
            ORDER BY id ASC
            FOR UPDATE
            """,
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _validate_batch_manifest(
        merchants: list[dict[str, Any]],
        manifest: list[dict[str, Any]],
    ) -> None:
        """Validate that locked merchant rows match the proposal manifest exactly."""
        if len(merchants) != len(manifest):
            raise MerchantConflictError(
                f"Manifest contains {len(manifest)} merchants but "
                f"database has {len(merchants)}"
            )

        for merchant_row, manifest_entry in zip(merchants, manifest):
            merchant_id = str(merchant_row.get("id", ""))
            manifest_id = str(manifest_entry.get("merchant_id", ""))

            if merchant_id != manifest_id:
                raise MerchantConflictError(
                    f"Manifest membership drift: expected merchant "
                    f"{manifest_id} but found {merchant_id}"
                )

            merchant_status = str(merchant_row.get("account_status", "")).upper()
            manifest_status = str(manifest_entry.get("account_status", "")).upper()

            if merchant_status != manifest_status:
                raise MerchantConflictError(
                    f"Merchant {merchant_id} status changed from "
                    f"{manifest_status} to {merchant_status}"
                )

            merchant_version = int(merchant_row.get("version", 0))
            manifest_version = int(manifest_entry.get("version", 0))

            if merchant_version != manifest_version:
                raise MerchantConflictError(
                    f"Merchant {merchant_id} version changed from "
                    f"{manifest_version} to {merchant_version}"
                )

    @staticmethod
    def _insert_merchant(
        cursor: Any,
        plan: MerchantCreationPlan,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO merchant_ops.merchants (
                id,
                code,
                name,
                region_code,
                account_status,
                created_at,
                updated_at,
                created_by,
                version
            )
            VALUES (
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                %s, %s
            )
            """,
            (
                uuid.UUID(plan.merchant_id),
                plan.code,
                plan.name,
                plan.region_code,
                plan.account_status,
                (
                    uuid.UUID(plan.created_by)
                    if plan.created_by is not None
                    else None
                ),
                plan.version,
            ),
        )

    @staticmethod
    def _insert_creation_event(
        cursor: Any,
        plan: MerchantCreationPlan,
        event_id: uuid.UUID,
    ) -> None:
        merchant_id = uuid.UUID(plan.merchant_id)
        cursor.execute(
            """
            INSERT INTO merchant_ops.project_events (
                id,
                merchant_id,
                project_id,
                event_type,
                entity_type,
                entity_id,
                change_summary,
                old_values,
                new_values,
                triggered_by,
                created_at
            )
            VALUES (
                %s, %s, NULL, %s, 'MERCHANT',
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                event_id,
                merchant_id,
                plan.event_type,
                merchant_id,
                plan.change_summary,
                Jsonb(plan.old_values),
                Jsonb(plan.new_values),
                (
                    uuid.UUID(plan.created_by)
                    if plan.created_by is not None
                    else None
                ),
            ),
        )

    @staticmethod
    def _lock_merchant(
        cursor: Any,
        merchant_id: uuid.UUID,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT
                merchant.id,
                merchant.code,
                merchant.account_status,
                merchant.version
            FROM merchant_ops.merchants AS merchant
            WHERE merchant.id = %s
            FOR UPDATE OF merchant
            """,
            (merchant_id,),
        )
        merchant = cursor.fetchone()

        if merchant is None:
            raise MerchantEntityNotFoundError(
                f"Merchant not found: {merchant_id}"
            )

        return dict(merchant)

    @staticmethod
    def _insert_contacts(
        cursor: Any,
        plan: ContactImportPlan,
    ) -> None:
        merchant_id = uuid.UUID(plan.merchant_id)

        for record in plan.records:
            cursor.execute(
                """
                INSERT INTO merchant_ops.merchant_contacts (
                    id,
                    merchant_id,
                    contact_type,
                    name,
                    email,
                    phone,
                    privacy_classification,
                    is_primary,
                    created_at,
                    version
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    CURRENT_TIMESTAMP, %s
                )
                """,
                (
                    uuid.UUID(record.contact_id),
                    merchant_id,
                    record.contact_type,
                    record.contact_name,
                    record.contact_email,
                    record.contact_phone,
                    record.privacy_classification,
                    record.is_primary,
                    record.version,
                ),
            )

    @staticmethod
    def _update_merchant_version(
        cursor: Any,
        plan: ContactImportPlan,
    ) -> None:
        cursor.execute(
            """
            UPDATE merchant_ops.merchants
            SET
                updated_at = CURRENT_TIMESTAMP,
                version = %s
            WHERE id = %s
              AND version = %s
            """,
            (
                plan.new_merchant_version,
                uuid.UUID(plan.merchant_id),
                plan.expected_version,
            ),
        )

        if cursor.rowcount != 1:
            raise MerchantVersionConflictError(
                "Merchant version changed before contacts "
                "could be committed"
            )

    @staticmethod
    def _insert_contact_event(
        cursor: Any,
        plan: ContactImportPlan,
        event_id: uuid.UUID,
    ) -> None:
        merchant_id = uuid.UUID(plan.merchant_id)
        cursor.execute(
            """
            INSERT INTO merchant_ops.project_events (
                id,
                merchant_id,
                project_id,
                event_type,
                entity_type,
                entity_id,
                change_summary,
                old_values,
                new_values,
                triggered_by,
                created_at
            )
            VALUES (
                %s, %s, NULL, %s, 'MERCHANT',
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                event_id,
                merchant_id,
                plan.event_type,
                merchant_id,
                plan.change_summary,
                Jsonb(plan.old_values),
                Jsonb(plan.new_values),
                (
                    uuid.UUID(plan.triggered_by)
                    if plan.triggered_by is not None
                    else None
                ),
            ),
        )

    @staticmethod
    def _update_merchant_status(
        cursor: Any,
        plan: MerchantActivationPlan,
    ) -> None:
        cursor.execute(
            """
            UPDATE merchant_ops.merchants
            SET
                account_status = %s,
                updated_at = CURRENT_TIMESTAMP,
                version = %s
            WHERE id = %s
              AND version = %s
            """,
            (
                plan.target_status,
                plan.new_merchant_version,
                uuid.UUID(plan.merchant_id),
                plan.expected_version,
            ),
        )

        if cursor.rowcount != 1:
            raise MerchantVersionConflictError(
                "Merchant version changed or status "
                "could not be updated"
            )

    @staticmethod
    def _insert_activation_event(
        cursor: Any,
        plan: MerchantActivationPlan,
        event_id: uuid.UUID,
    ) -> None:
        merchant_id = uuid.UUID(plan.merchant_id)
        # Include reason in audit event
        new_values = dict(plan.new_values)
        new_values["reason"] = plan.reason
        old_values = dict(plan.old_values)
        old_values["reason"] = plan.reason
        cursor.execute(
            """
            INSERT INTO merchant_ops.project_events (
                id,
                merchant_id,
                project_id,
                event_type,
                entity_type,
                entity_id,
                change_summary,
                old_values,
                new_values,
                triggered_by,
                created_at
            )
            VALUES (
                %s, %s, NULL, %s, 'MERCHANT',
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                event_id,
                merchant_id,
                plan.event_type,
                merchant_id,
                plan.change_summary,
                Jsonb(old_values),
                Jsonb(new_values),
                (
                    uuid.UUID(plan.triggered_by)
                    if plan.triggered_by is not None
                    else None
                ),
            ),
        )


def _uuid(value: Any, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise MerchantPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error
