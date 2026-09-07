"""Deterministic propose/apply boundary for Merchant mutations."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from .cli_contract import (
    CONTRACT_VERSION,
    COMMAND_SENSITIVE_FIELDS,
    WRITE_COMMANDS,
    CommandNotAllowedError,
    MerchantCliContractError,
    build_proposal,
    normalize_command,
    normalize_database_target,
    redact_payload,
    require_apply_authorization,
    to_json_value,
    verify_proposal_hash,
)


PROPOSAL_ID_NAMESPACE = uuid.UUID(
    "60f77b9c-8fb2-54bf-9466-3c32c43e9299"
)

GENERATED_ID_FIELDS = MappingProxyType(
    {
        "document approve": "approval_id",
        "document revision-create": "revision_id",
        "merchant create": "merchant_id",
        "procurement update": "procurement_id",
        "project create": "project_id",
    }
)

WriteHandler = Callable[[dict[str, Any]], Any]


class WriteCommandNotConfiguredError(
    MerchantCliContractError
):
    """Raised when an allowlisted write has no local handler."""


class MerchantWriteCommands:
    """Propose exact payloads and apply only matching requests."""

    def __init__(
        self,
        handlers: Mapping[str, WriteHandler],
    ) -> None:
        configured: dict[str, WriteHandler] = {}

        for command, handler in handlers.items():
            normalized_command = normalize_command(command)

            if normalized_command not in WRITE_COMMANDS:
                raise CommandNotAllowedError(
                    "Write handlers must use write commands"
                )

            if normalized_command in configured:
                raise WriteCommandNotConfiguredError(
                    "Duplicate write handler after normalization: "
                    f"{normalized_command}"
                )

            if not callable(handler):
                raise WriteCommandNotConfiguredError(
                    "Write handler must be callable: "
                    f"{normalized_command}"
                )

            configured[normalized_command] = handler

        self._handlers = MappingProxyType(configured)

    @property
    def configured_commands(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def propose(
        self,
        command: str,
        database: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return a redacted proposal without invoking its handler."""

        normalized_command = normalize_command(command)
        self._handler(normalized_command)
        prepared_payload = materialize_write_payload(
            normalized_command,
            database,
            payload,
        )
        proposal = build_proposal(
            normalized_command,
            database,
            prepared_payload,
        )
        return {
            "success": True,
            **proposal.to_dict(),
        }

    def apply(
        self,
        command: str,
        database: str,
        payload: Mapping[str, Any],
        *,
        proposal_hash: str,
        runtime_authorization: Any = None,
    ) -> dict[str, Any]:
        """Verify authority and proposal binding before one mutation."""

        normalized_command = normalize_command(command)
        normalized_database = normalize_database_target(database)
        handler = self._handler(normalized_command)
        prepared_payload = materialize_write_payload(
            normalized_command,
            normalized_database,
            payload,
        )

        require_apply_authorization(
            normalized_command,
            normalized_database,
            runtime_authorization=runtime_authorization,
            payload=prepared_payload,
            proposal_hash=proposal_hash,
        )
        verify_proposal_hash(
            proposal_hash,
            normalized_command,
            normalized_database,
            prepared_payload,
        )

        result = handler(to_json_value(prepared_payload))
        sensitive_fields = COMMAND_SENSITIVE_FIELDS.get(
            normalized_command,
            frozenset(),
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "success": True,
            "mode": "APPLY",
            "command": normalized_command,
            "database": normalized_database,
            "proposal_hash": proposal_hash.strip().lower(),
            "result": redact_payload(
                result,
                extra_sensitive_fields=sensitive_fields,
            ),
        }

    def _handler(self, command: str) -> WriteHandler:
        handler = self._handlers.get(command)

        if handler is None:
            raise WriteCommandNotConfiguredError(
                f"Write command is not configured: {command}"
            )

        return handler


def materialize_write_payload(
    command: str,
    database: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Add stable internal IDs before proposal hashing."""

    normalized_command = normalize_command(command)

    if normalized_command not in WRITE_COMMANDS:
        raise CommandNotAllowedError(
            "Only write commands have mutation payloads"
        )

    normalized_database = normalize_database_target(database)
    normalized_payload = to_json_value(payload)

    if not isinstance(normalized_payload, dict):
        raise MerchantCliContractError(
            "write payload must be an object"
        )

    materialized = _copy_json_object(normalized_payload)
    generated_field = GENERATED_ID_FIELDS.get(
        normalized_command
    )

    if (
        generated_field is not None
        and materialized.get(generated_field) is None
    ):
        materialized[generated_field] = _stable_id(
            normalized_command,
            normalized_database,
            normalized_payload,
            generated_field,
        )

    if normalized_command == "contact import":
        _materialize_contact_ids(
            normalized_command,
            normalized_database,
            normalized_payload,
            materialized,
        )

    return materialized


def _materialize_contact_ids(
    command: str,
    database: str,
    seed_payload: dict[str, Any],
    materialized: dict[str, Any],
) -> None:
    contacts = materialized.get("contacts")

    if not isinstance(contacts, list):
        raise MerchantCliContractError(
            "contact import payload requires a contacts array"
        )

    for index, contact in enumerate(contacts):
        if not isinstance(contact, dict):
            raise MerchantCliContractError(
                "contact import rows must be objects"
            )

        if (
            contact.get("contact_id") is None
            and contact.get("id") is None
        ):
            contact["contact_id"] = _stable_id(
                command,
                database,
                seed_payload,
                f"contact:{index}",
            )


def _stable_id(
    command: str,
    database: str,
    payload: dict[str, Any],
    label: str,
) -> str:
    canonical_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload_digest = hashlib.sha256(
        canonical_payload.encode("utf-8")
    ).hexdigest()
    name = "|".join(
        (
            str(CONTRACT_VERSION),
            command,
            database,
            label,
            payload_digest,
        )
    )
    return str(uuid.uuid5(PROPOSAL_ID_NAMESPACE, name))


def _copy_json_object(value: dict[str, Any]) -> dict[str, Any]:
    copied = to_json_value(value)

    if not isinstance(copied, dict):  # pragma: no cover
        raise MerchantCliContractError(
            "write payload must be an object"
        )

    return copied
