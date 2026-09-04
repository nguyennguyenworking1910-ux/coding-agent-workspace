"""Immutable PostgreSQL loader for Merchant workflow templates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from psycopg.rows import dict_row

from claude.agents.tools.merchant.workflow import (
    WorkflowTemplateDefinition,
    template_dependency_uuid,
    template_fingerprint,
    template_payload,
    template_step_uuid,
    template_uuid,
)
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)
from claude.clients.merchant.repository import MerchantRepository


class WorkflowTemplateLoadError(RuntimeError):
    """Base error raised by the workflow-template loader."""


class WorkflowTemplateConflictError(WorkflowTemplateLoadError):
    """Raised when an immutable template differs from stored data."""


@dataclass(frozen=True, slots=True)
class WorkflowTemplateLoadResult:
    """Summary of one template-loading transaction."""

    templates_inserted: int = 0
    templates_unchanged: int = 0
    steps_inserted: int = 0
    dependencies_inserted: int = 0

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-compatible result."""

        return asdict(self)


class WorkflowTemplateLoader:
    """Load immutable workflow definitions into PostgreSQL."""

    def __init__(self, repository: MerchantRepository) -> None:
        self.repository = repository

    def load_standard_templates(
        self,
    ) -> WorkflowTemplateLoadResult:
        """Load every built-in workflow template."""

        return self.load_templates(STANDARD_WORKFLOW_TEMPLATES)

    def load_templates(
        self,
        templates: Sequence[WorkflowTemplateDefinition],
    ) -> WorkflowTemplateLoadResult:
        """Insert missing templates and reject stored differences."""

        selected_templates = tuple(templates)
        self._validate_input(selected_templates)

        if not selected_templates:
            return WorkflowTemplateLoadResult()

        templates_inserted = 0
        templates_unchanged = 0
        steps_inserted = 0
        dependencies_inserted = 0

        with self.repository.connection() as connection:
            with connection.transaction():
                with connection.cursor(
                    row_factory=dict_row,
                ) as cursor:
                    for template in selected_templates:
                        # Serialize loaders operating on the same immutable
                        # template identity without locking unrelated ones.
                        cursor.execute(
                            """
                            SELECT pg_advisory_xact_lock(
                                hashtext(%s)
                            )
                            """,
                            (
                                self._lock_key(template),
                            ),
                        )

                        inserted = self._load_one(
                            cursor,
                            template,
                        )

                        if inserted:
                            templates_inserted += 1
                            steps_inserted += len(template.steps)
                            dependencies_inserted += len(
                                template.dependencies
                            )
                        else:
                            templates_unchanged += 1

        return WorkflowTemplateLoadResult(
            templates_inserted=templates_inserted,
            templates_unchanged=templates_unchanged,
            steps_inserted=steps_inserted,
            dependencies_inserted=dependencies_inserted,
        )

    @staticmethod
    def _validate_input(
        templates: Sequence[WorkflowTemplateDefinition],
    ) -> None:
        identities: set[tuple[str, int]] = set()
        template_ids: set[str] = set()

        for template in templates:
            # These functions validate and canonicalize the complete
            # workflow definition before database access.
            template_payload(template)
            template_fingerprint(template)

            identity = (template.name, template.version)
            stable_id = str(template_uuid(template))

            if identity in identities:
                raise WorkflowTemplateLoadError(
                    "Duplicate workflow template identity in input: "
                    f"{template.name!r} version {template.version}"
                )

            if stable_id in template_ids:
                raise WorkflowTemplateLoadError(
                    "Duplicate deterministic workflow template UUID "
                    f"in input: {stable_id}"
                )

            identities.add(identity)
            template_ids.add(stable_id)

    def _load_one(
        self,
        cursor: Any,
        template: WorkflowTemplateDefinition,
    ) -> bool:
        cursor.execute(
            """
            SELECT
                id,
                name,
                version,
                description,
                variant,
                is_active
            FROM merchant_ops.workflow_templates
            WHERE name = %s
              AND version = %s
            FOR UPDATE
            """,
            (
                template.name,
                template.version,
            ),
        )

        existing_template = cursor.fetchone()

        if existing_template is not None:
            self._assert_existing_matches(
                cursor,
                template,
                dict(existing_template),
            )
            return False

        self._assert_stable_id_available(cursor, template)
        self._insert_template(cursor, template)
        self._insert_steps(cursor, template)
        self._insert_dependencies(cursor, template)

        return True

    @staticmethod
    def _assert_stable_id_available(
        cursor: Any,
        template: WorkflowTemplateDefinition,
    ) -> None:
        stable_id = template_uuid(template)

        cursor.execute(
            """
            SELECT name, version
            FROM merchant_ops.workflow_templates
            WHERE id = %s
            """,
            (stable_id,),
        )

        existing = cursor.fetchone()

        if existing is not None:
            existing_record = dict(existing)

            raise WorkflowTemplateConflictError(
                "Deterministic workflow template UUID already belongs "
                "to another record: "
                f"id={stable_id}, "
                f"name={existing_record['name']!r}, "
                f"version={existing_record['version']}"
            )

    @staticmethod
    def _insert_template(
        cursor: Any,
        template: WorkflowTemplateDefinition,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO merchant_ops.workflow_templates (
                id,
                name,
                version,
                description,
                variant,
                is_active,
                created_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                template_uuid(template),
                template.name,
                template.version,
                template.description,
                template.variant,
                template.is_active,
            ),
        )

    @staticmethod
    def _insert_steps(
        cursor: Any,
        template: WorkflowTemplateDefinition,
    ) -> None:
        query = """
            INSERT INTO merchant_ops.workflow_template_steps (
                id,
                template_id,
                sequence_number,
                branch_key,
                step_type,
                name,
                description,
                is_optional,
                condition_key,
                created_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
        """

        stable_template_id = template_uuid(template)

        for step in template.steps:
            cursor.execute(
                query,
                (
                    template_step_uuid(template, step.key),
                    stable_template_id,
                    step.sequence_number,
                    step.branch_key,
                    step.step_type,
                    step.name,
                    step.description,
                    step.is_optional,
                    step.condition_key,
                ),
            )

    @staticmethod
    def _insert_dependencies(
        cursor: Any,
        template: WorkflowTemplateDefinition,
    ) -> None:
        query = """
            INSERT INTO
                merchant_ops.workflow_template_dependencies (
                    id,
                    from_step_id,
                    to_step_id,
                    dependency_type,
                    created_at
                )
            VALUES (
                %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
        """

        for dependency in template.dependencies:
            cursor.execute(
                query,
                (
                    template_dependency_uuid(
                        template,
                        dependency,
                    ),
                    template_step_uuid(
                        template,
                        dependency.from_step_key,
                    ),
                    template_step_uuid(
                        template,
                        dependency.to_step_key,
                    ),
                    dependency.dependency_type,
                ),
            )

    def _assert_existing_matches(
        self,
        cursor: Any,
        template: WorkflowTemplateDefinition,
        existing_template: dict[str, Any],
    ) -> None:
        expected_template = self._expected_template_record(
            template
        )
        actual_template = self._normalize_template_record(
            existing_template
        )

        differences: list[str] = []

        if actual_template != expected_template:
            differences.append("template metadata")

        cursor.execute(
            """
            SELECT
                id,
                template_id,
                sequence_number,
                branch_key,
                step_type,
                name,
                description,
                is_optional,
                condition_key
            FROM merchant_ops.workflow_template_steps
            WHERE template_id = %s
            ORDER BY sequence_number, id
            """,
            (template_uuid(template),),
        )

        actual_steps = self._normalize_records(
            cursor.fetchall(),
            sort_fields=("sequence_number", "id"),
        )
        expected_steps = self._expected_step_records(template)

        if actual_steps != expected_steps:
            differences.append("template steps")

        cursor.execute(
            """
            SELECT
                dependency.id,
                dependency.from_step_id,
                dependency.to_step_id,
                dependency.dependency_type
            FROM
                merchant_ops.workflow_template_dependencies
                    AS dependency
            JOIN merchant_ops.workflow_template_steps AS source
              ON source.id = dependency.from_step_id
            JOIN merchant_ops.workflow_template_steps AS destination
              ON destination.id = dependency.to_step_id
            WHERE source.template_id = %s
              AND destination.template_id = %s
            ORDER BY
                dependency.from_step_id,
                dependency.to_step_id,
                dependency.dependency_type,
                dependency.id
            """,
            (
                template_uuid(template),
                template_uuid(template),
            ),
        )

        actual_dependencies = self._normalize_records(
            cursor.fetchall(),
            sort_fields=(
                "from_step_id",
                "to_step_id",
                "dependency_type",
                "id",
            ),
        )
        expected_dependencies = (
            self._expected_dependency_records(template)
        )

        if actual_dependencies != expected_dependencies:
            differences.append("template dependencies")

        if differences:
            joined_differences = ", ".join(differences)

            raise WorkflowTemplateConflictError(
                "Stored workflow template differs from immutable "
                "definition: "
                f"{template.name!r} version {template.version}; "
                f"differing sections: {joined_differences}; "
                f"expected fingerprint: "
                f"{template_fingerprint(template)}"
            )

    @staticmethod
    def _expected_template_record(
        template: WorkflowTemplateDefinition,
    ) -> dict[str, Any]:
        return {
            "id": str(template_uuid(template)),
            "name": template.name,
            "version": template.version,
            "description": template.description,
            "variant": template.variant,
            "is_active": template.is_active,
        }

    @staticmethod
    def _normalize_template_record(
        record: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": str(record["id"]),
            "name": record["name"],
            "version": record["version"],
            "description": record["description"],
            "variant": record["variant"],
            "is_active": record["is_active"],
        }

    @staticmethod
    def _expected_step_records(
        template: WorkflowTemplateDefinition,
    ) -> list[dict[str, Any]]:
        template_id = str(template_uuid(template))

        records = [
            {
                "id": str(
                    template_step_uuid(template, step.key)
                ),
                "template_id": template_id,
                "sequence_number": step.sequence_number,
                "branch_key": step.branch_key,
                "step_type": step.step_type,
                "name": step.name,
                "description": step.description,
                "is_optional": step.is_optional,
                "condition_key": step.condition_key,
            }
            for step in template.steps
        ]

        return sorted(
            records,
            key=lambda record: (
                record["sequence_number"],
                record["id"],
            ),
        )

    @staticmethod
    def _expected_dependency_records(
        template: WorkflowTemplateDefinition,
    ) -> list[dict[str, Any]]:
        records = [
            {
                "id": str(
                    template_dependency_uuid(
                        template,
                        dependency,
                    )
                ),
                "from_step_id": str(
                    template_step_uuid(
                        template,
                        dependency.from_step_key,
                    )
                ),
                "to_step_id": str(
                    template_step_uuid(
                        template,
                        dependency.to_step_key,
                    )
                ),
                "dependency_type":
                    dependency.dependency_type,
            }
            for dependency in template.dependencies
        ]

        return sorted(
            records,
            key=lambda record: (
                record["from_step_id"],
                record["to_step_id"],
                record["dependency_type"],
                record["id"],
            ),
        )

    @staticmethod
    def _normalize_records(
        records: Iterable[dict[str, Any]],
        *,
        sort_fields: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        normalized = []

        for source_record in records:
            record = dict(source_record)

            for key in (
                "id",
                "template_id",
                "from_step_id",
                "to_step_id",
            ):
                if key in record:
                    record[key] = str(record[key])

            normalized.append(record)

        return sorted(
            normalized,
            key=lambda record: tuple(
                record[field]
                for field in sort_fields
            ),
        )

    @staticmethod
    def _lock_key(
        template: WorkflowTemplateDefinition,
    ) -> str:
        return (
            "merchant-workflow-template:"
            f"{template.name}:"
            f"{template.version}"
        )


def load_standard_workflow_templates(
    repository: MerchantRepository,
) -> WorkflowTemplateLoadResult:
    """Load the built-in templates through a repository."""

    return WorkflowTemplateLoader(
        repository
    ).load_standard_templates()