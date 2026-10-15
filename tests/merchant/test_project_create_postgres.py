import os
import uuid

import pytest

from claude.agents.tools.merchant.workflow import template_uuid
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import (
    MerchantWorkflowRepository,
    ProjectCreationConflictError,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME")
    != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)

TEMPLATE = next(
    template
    for template in STANDARD_WORKFLOW_TEMPLATES
    if template.name == "OPENING_NEW_CINEMA_STANDARD"
)


@pytest.fixture
def repository():
    return MerchantRepository(role="test")


@pytest.fixture
def installed_template(repository):
    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM merchant_ops.workflow_templates
                WHERE id = %s
                """,
                (template_uuid(TEMPLATE),),
            )
            row = cursor.fetchone()

    if row is None:
        pytest.skip(
            "OPENING_NEW_CINEMA_STANDARD is not installed in "
            "coding_agent_merchant_test; run the template loader first"
        )

    return TEMPLATE


@pytest.fixture
def merchant(repository):
    # Seed a test-owned ACTIVE merchant; the database has none.
    merchant_id = str(uuid.uuid4())
    code = f"T{uuid.uuid4().hex[:18].upper()}"

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.merchants (
                        id,
                        code,
                        name,
                        account_status,
                        version
                    )
                    VALUES (%s, %s, %s, 'ACTIVE', 1)
                    """,
                    (
                        uuid.UUID(merchant_id),
                        code,
                        f"Project create test {code}",
                    ),
                )

    yield {"merchant_id": merchant_id, "code": code}

    delete_records_for_merchant(repository, merchant_id)


def delete_records_for_merchant(repository, merchant_id):
    # Scoped strictly to the merchant this test seeded.
    merchant_uuid = uuid.UUID(merchant_id)

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.project_step_dependencies
                    WHERE from_step_id IN (
                        SELECT step.id
                        FROM merchant_ops.project_steps AS step
                        JOIN merchant_ops.projects AS project
                          ON project.id = step.project_id
                        WHERE project.merchant_id = %s
                    )
                    """,
                    (merchant_uuid,),
                )
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.project_steps
                    WHERE project_id IN (
                        SELECT id
                        FROM merchant_ops.projects
                        WHERE merchant_id = %s
                    )
                    """,
                    (merchant_uuid,),
                )
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                    """,
                    (merchant_uuid,),
                )
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.projects
                    WHERE merchant_id = %s
                    """,
                    (merchant_uuid,),
                )
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (merchant_uuid,),
                )


def project_counts(repository, project_id):
    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM merchant_ops.projects
                     WHERE id = %s) AS projects,
                    (SELECT COUNT(*) FROM merchant_ops.project_steps
                     WHERE project_id = %s) AS steps,
                    (SELECT COUNT(*) FROM merchant_ops.project_events
                     WHERE project_id = %s) AS events,
                    (SELECT COUNT(*)
                     FROM merchant_ops.project_step_dependencies
                          AS dependency
                     JOIN merchant_ops.project_steps AS step
                       ON step.id = dependency.from_step_id
                     WHERE step.project_id = %s) AS dependencies
                """,
                (
                    uuid.UUID(project_id),
                    uuid.UUID(project_id),
                    uuid.UUID(project_id),
                    uuid.UUID(project_id),
                ),
            )
            return dict(cursor.fetchone())


def test_active_merchant_creates_opening_project(
    repository,
    installed_template,
    merchant,
):
    workflow = MerchantWorkflowRepository(repository)
    merchant_id = merchant["merchant_id"]
    project_id = str(uuid.uuid4())

    result = workflow.create_project(
        merchant_id=merchant_id,
        template=installed_template,
        requires_procurement=False,
        project_id=project_id,
        title=f"pytest project {project_id}",
    )

    assert result.project_id == project_id
    assert result.merchant_id == merchant_id
    assert result.workflow_variant == "OPENING_NEW_CINEMA_STANDARD"
    assert result.status == "PLANNED"
    assert result.steps_inserted == 22
    assert result.dependencies_inserted == 22

    snapshot = repository.get_project_snapshot(project_id)
    project = snapshot["project"]

    assert str(project["merchant_id"]) == merchant_id
    assert project["merchant_code"] == merchant["code"]
    assert project["project_type"] == "OPENING_NEW_CINEMA"
    assert project["status"] == "PLANNED"

    steps = snapshot["steps"]
    step_ids = {str(step["id"]) for step in steps}

    assert len(steps) == 22
    assert all(
        str(step["project_id"]) == project_id for step in steps
    )

    dependencies = snapshot["dependencies"]

    assert len(dependencies) == 22
    assert all(
        str(dependency["from_step_id"]) in step_ids
        and str(dependency["to_step_id"]) in step_ids
        for dependency in dependencies
    )

    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type, entity_type, entity_id, merchant_id
                FROM merchant_ops.project_events
                WHERE project_id = %s
                """,
                (uuid.UUID(project_id),),
            )
            events = cursor.fetchall()

    assert len(events) == 1
    assert events[0]["event_type"] == "PROJECT_CREATED"
    assert events[0]["entity_type"] == "PROJECT"
    assert str(events[0]["entity_id"]) == project_id
    assert str(events[0]["merchant_id"]) == merchant_id


def test_failed_project_creation_rolls_back_all_writes(
    repository,
    installed_template,
    merchant,
    monkeypatch,
):
    workflow = MerchantWorkflowRepository(repository)
    project_id = str(uuid.uuid4())
    seen = {}

    def fail_event_insert(cursor, plan):
        # Dependencies were written earlier in this same transaction.
        cursor.execute(
            """
            SELECT COUNT(*) AS n
            FROM merchant_ops.project_step_dependencies AS dependency
            JOIN merchant_ops.project_steps AS step
              ON step.id = dependency.from_step_id
            WHERE step.project_id = %s
            """,
            (uuid.UUID(project_id),),
        )
        seen["dependencies"] = cursor.fetchone()["n"]
        raise RuntimeError("Injected event write failure")

    # Fail after the project, steps and dependencies were written
    # inside the same transaction.
    monkeypatch.setattr(
        MerchantWorkflowRepository,
        "_insert_event",
        staticmethod(fail_event_insert),
    )

    with pytest.raises(
        RuntimeError,
        match="Injected event write failure",
    ):
        workflow.create_project(
            merchant_id=merchant["merchant_id"],
            template=installed_template,
            requires_procurement=False,
            project_id=project_id,
        )

    assert seen["dependencies"] == 22
    assert project_counts(repository, project_id) == {
        "projects": 0,
        "steps": 0,
        "dependencies": 0,
        "events": 0,
    }


def test_duplicate_project_id_is_rejected_without_altering_original(
    repository,
    installed_template,
    merchant,
):
    workflow = MerchantWorkflowRepository(repository)
    project_id = str(uuid.uuid4())
    original_title = f"pytest original {project_id}"

    workflow.create_project(
        merchant_id=merchant["merchant_id"],
        template=installed_template,
        requires_procurement=False,
        project_id=project_id,
        title=original_title,
    )

    before = project_counts(repository, project_id)

    assert before == {
        "projects": 1,
        "steps": 22,
        "dependencies": 22,
        "events": 1,
    }

    with pytest.raises(
        ProjectCreationConflictError,
        match="already exists",
    ):
        workflow.create_project(
            merchant_id=merchant["merchant_id"],
            template=installed_template,
            requires_procurement=False,
            project_id=project_id,
            title="pytest duplicate attempt",
        )

    assert project_counts(repository, project_id) == before

    snapshot = repository.get_project_snapshot(project_id)

    assert snapshot["project"]["title"] == original_title
