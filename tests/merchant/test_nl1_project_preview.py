"""CP12H.NL1: natural-language Project preview (pure, fake read-only reader)."""

from __future__ import annotations

import copy
import uuid

import pytest

from claude.agents.tools.merchant import project_preview
from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    prepare_agent_cli_argv,
)
from claude.agents.tools.merchant.cli_contract import READ_COMMANDS
from claude.agents.tools.merchant.project_nl import (
    MERCHANT_CREATE,
    MIXED,
    PROJECT_CREATE,
    PROJECT_LIST,
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.project_preview import (
    BLOCKED,
    NEEDS_CLARIFICATION,
    NOT_PROJECT_CREATION,
    READY,
    build_project_preview,
)
from claude.agents.tools.merchant.workflow import template_uuid
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)
from claude.hooks import merchant_direct_handoff, policy_gate


BETA = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
LOTTE = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
BETA_MEDIA = str(uuid.UUID("33333333-3333-4333-8333-333333333333"))

CREATE_EXAMPLES = (
    "Tạo project mở rạp Beta Nguyễn Văn Cừ.",
    "Tạo dự án khai trương rạp Nguyễn Văn Cừ cho Beta.",
    "Create a new cinema opening project for Beta Nguyễn Văn Cừ.",
    "Create a project to open Beta Nguyễn Văn Cừ cinema",
)
NO_PROCUREMENT = " Không cần mua sắm."


class Reader:
    """Read-only fake. Any other attribute access fails the test."""

    def __init__(self, merchants=None, projects=None, installed=True):
        self.merchants = merchants if merchants is not None else [
            merchant(BETA, "BETA", "Beta Cinemas"),
            merchant(LOTTE, "LOTTE", "Lotte Cinema"),
        ]
        self.projects = projects or []
        self.installed = installed
        self.calls = []

    def list_merchants(self):
        self.calls.append("list_merchants")
        return copy.deepcopy(self.merchants)

    def list_projects(self, *, merchant_id=None, status=None):
        self.calls.append("list_projects")
        return [
            dict(project)
            for project in self.projects
            if merchant_id is None or project["merchant_id"] == merchant_id
        ]

    def get_workflow_template(self, template_id):
        self.calls.append("get_workflow_template")
        if not self.installed:
            return None
        for template in STANDARD_WORKFLOW_TEMPLATES:
            if str(template_uuid(template)) == template_id:
                return {
                    "id": template_id,
                    "name": template.name,
                    "version": template.version,
                    "variant": template.variant,
                    "is_active": True,
                }
        return None

    def __getattr__(self, name):
        raise AssertionError(f"preview used a non-read API: {name}")


def merchant(merchant_id, code, name, status="ACTIVE", version=1):
    return {
        "id": merchant_id,
        "code": code,
        "name": name,
        "account_status": status,
        "version": version,
    }


def project(title, status="IN_PROGRESS", merchant_id=BETA):
    return {
        "id": str(uuid.uuid4()),
        "merchant_id": merchant_id,
        "title": title,
        "project_type": "OPENING_NEW_CINEMA",
        "workflow_variant": "OPENING_NEW_CINEMA_STANDARD",
        "status": status,
        "version": 1,
    }


# ---------------------------------------------------------------- Phase 2


@pytest.mark.parametrize("request_text", CREATE_EXAMPLES)
def test_creation_paraphrases_are_project_creation_not_merchant_creation(
    request_text,
):
    result = interpret_project_request(request_text)

    assert result.kind == PROJECT_CREATE
    assert result.project_type == "OPENING_NEW_CINEMA"
    assert result.write_requested is True


@pytest.mark.parametrize(
    ("request_text", "kind", "phrase"),
    (
        ("Các dự án hiện tại của Beta là gì?", PROJECT_LIST, "Beta"),
        ("What are Beta's current projects?", PROJECT_LIST, None),
        ("Project Beta Nguyễn Văn Cừ đang ở bước nào?", PROJECT_STATUS,
         "Beta Nguyễn Văn Cừ"),
        ("Which step is the project Beta Nguyễn Văn Cừ at?", PROJECT_STATUS,
         "Beta Nguyễn Văn Cừ"),
        ("Tạo merchant Beta mới", MERCHANT_CREATE, None),
        ("Create a new merchant called Beta Cinemas", MERCHANT_CREATE, None),
        ("Cập nhật bước Legal review của project Beta sang hoàn thành",
         STEP_UPDATE, None),
        ("Mark the legal review step of Beta Nguyễn Văn Cừ complete",
         STEP_UPDATE, None),
        ("Create a new merchant Beta and a cinema opening project",
         MIXED, None),
    ),
)
def test_lookup_status_step_and_merchant_requests_are_distinguished(
    request_text, kind, phrase
):
    result = interpret_project_request(request_text)

    assert result.kind == kind
    if kind in (PROJECT_LIST, PROJECT_STATUS):
        assert result.write_requested is False
    if kind == PROJECT_LIST and phrase:
        assert result.merchant_phrase == phrase
    if kind == PROJECT_STATUS:
        assert result.project_phrase == phrase


@pytest.mark.parametrize(
    "request_text",
    (
        "Không tạo project, chỉ xem trước dự án mở rạp Beta Nguyễn Văn Cừ",
        "Đừng tạo dự án mở rạp Beta Nguyễn Văn Cừ",
        "Do not create the cinema opening project for Beta Nguyễn Văn Cừ",
        "Preview a cinema opening project for Beta Nguyễn Văn Cừ",
        "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ",
        "Should we create a cinema opening project for Beta Nguyễn Văn Cừ?",
        "Có nên tạo project mở rạp Beta Nguyễn Văn Cừ không?",
    ),
)
def test_negated_preview_and_exploratory_wording_never_requests_a_write(
    request_text,
):
    result = interpret_project_request(request_text)

    assert result.kind == PROJECT_CREATE
    assert result.write_requested is False


# ---------------------------------------------------------- Phases 3 and 4


@pytest.mark.parametrize("request_text", CREATE_EXAMPLES)
def test_paraphrases_resolve_the_existing_merchant_and_one_template(
    request_text,
):
    preview = build_project_preview(request_text + NO_PROCUREMENT, Reader())

    assert preview["outcome"] == READY, preview["clarifications"]
    assert preview["merchant"]["merchant_id"] == BETA
    assert preview["merchant"]["name"] == "Beta Cinemas"
    assert preview["fields"] == {
        "merchant_id": BETA,
        "merchant_code": "BETA",  # CP12H.NL2E P2: confirmed with the operation
        "project_type": "OPENING_NEW_CINEMA",
        "workflow_variant": "OPENING_NEW_CINEMA_STANDARD",
        "title": "Beta Nguyễn Văn Cừ",
        "requires_procurement": False,
    }
    operation = preview["requested_operation"]
    assert operation["command"] == "project create"
    assert operation["argv"][:2] == ["project", "create"]
    assert "merchant" not in operation["argv"][:1]


def test_initial_steps_come_from_the_real_template_and_factory():
    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader())

    template = next(
        t for t in STANDARD_WORKFLOW_TEMPLATES
        if t.variant == "OPENING_NEW_CINEMA_STANDARD"
    )
    steps = preview["initial_steps"]
    assert [step["name"] for step in steps] == [
        step.name
        for step in sorted(template.steps, key=lambda s: s.sequence_number)
    ]
    procurement = [s for s in steps if s["branch_key"] == "procurement_branch"]
    assert procurement and all(s["initial_status"] == "SKIPPED" for s in procurement)
    assert preview["project"]["template"]["installed"] is True
    assert preview["project"]["template"]["template_id"] == str(
        template_uuid(template)
    )


def test_procurement_is_asked_not_invented():
    preview = build_project_preview(CREATE_EXAMPLES[0], Reader())

    assert preview["outcome"] == NEEDS_CLARIFICATION
    assert preview["missing_fields"] == ["requires_procurement"]
    assert preview["requested_operation"] is None
    assert all(step["initial_status"] is None for step in preview["initial_steps"])

    with_pr = build_project_preview(
        "Tạo project mở rạp Beta Nguyễn Văn Cừ, có mua sắm", Reader()
    )
    assert with_pr["fields"]["requires_procurement"] is True
    assert "--requires-procurement" in with_pr["requested_operation"]["argv"]


def test_ambiguous_merchant_requires_clarification():
    # Codes differ from "beta"; an exact code match would win by precedence.
    reader = Reader(merchants=[
        merchant(BETA, "BETA_CINEMAS", "Beta Cinemas"),
        merchant(BETA_MEDIA, "BETA_MEDIA", "Beta Media"),
    ])

    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, reader)

    assert preview["outcome"] == NEEDS_CLARIFICATION
    assert preview["merchant"] is None
    assert preview["requested_operation"] is None
    assert "several Merchants" in preview["clarifications"][0]


def test_unknown_merchant_is_never_created():
    preview = build_project_preview(
        "Tạo project mở rạp Galaxy Nguyễn Du. Không cần mua sắm.", Reader()
    )

    assert preview["outcome"] == NEEDS_CLARIFICATION
    assert preview["merchant"] is None
    assert "never creates a Merchant" in preview["clarifications"][0]
    assert preview["requested_operation"] is None


def test_merchant_creation_request_builds_no_project_preview():
    preview = build_project_preview("Tạo merchant Beta mới", Reader())

    assert preview["outcome"] == NOT_PROJECT_CREATION
    assert preview["requested_operation"] is None


def test_inactive_merchant_fails_the_template_precondition():
    reader = Reader(merchants=[merchant(BETA, "BETA", "Beta Cinemas", "ONBOARDING")])

    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, reader)

    assert preview["outcome"] == BLOCKED
    assert preview["conflicts"][0]["kind"] == "MERCHANT_PRECONDITION"
    assert preview["requested_operation"] is None


def test_template_not_installed_blocks():
    preview = build_project_preview(
        CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader(installed=False)
    )

    assert preview["outcome"] == BLOCKED
    assert preview["conflicts"][0]["kind"] == "TEMPLATE_NOT_INSTALLED"
    assert preview["requested_operation"] is None


def test_invalid_or_ambiguous_template_requires_clarification():
    invalid = build_project_preview(
        "Tạo project cho Beta Nguyễn Văn Cừ", Reader(), project_type_hint="CINEMA"
    )
    assert invalid["outcome"] == NEEDS_CLARIFICATION
    assert invalid["fields"]["workflow_variant"] is None

    media = build_project_preview(
        "Tạo project media top up cho Beta", Reader(), title_hint="Q3 top up"
    )
    assert media["outcome"] == NEEDS_CLARIFICATION
    assert media["fields"]["workflow_variant"] is None
    assert "MEDIA_TOP_UP_EXISTING_DOCUMENT" in " ".join(media["clarifications"])


@pytest.mark.parametrize(
    "existing_title",
    ("Mở rạp Beta Nguyễn Văn Cừ", "Beta Nguyen Van Cu", "Nguyễn Văn Cừ"),
)
def test_possible_duplicate_project_blocks(existing_title):
    reader = Reader(projects=[project(existing_title)])

    preview = build_project_preview(CREATE_EXAMPLES[1] + NO_PROCUREMENT, reader)

    assert preview["outcome"] == BLOCKED
    assert preview["conflicts"][0]["kind"] == "POSSIBLE_DUPLICATE_PROJECT"
    assert preview["requested_operation"] is None


def test_cancelled_duplicate_and_other_merchant_projects_do_not_block():
    reader = Reader(projects=[
        project("Beta Nguyễn Văn Cừ", status="CANCELLED"),
        project("Beta Nguyễn Văn Cừ", merchant_id=LOTTE),
    ])

    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, reader)

    assert preview["outcome"] == READY
    assert [c["blocking"] for c in preview["conflicts"]] == [False]


def test_stale_or_conflicting_merchant_candidate_is_rejected():
    stale = build_project_preview(
        CREATE_EXAMPLES[0] + NO_PROCUREMENT,
        Reader(),
        merchant_hint=str(uuid.uuid4()),
    )
    assert stale["outcome"] == NEEDS_CLARIFICATION
    assert stale["merchant"] is None

    other = build_project_preview(
        CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader(), merchant_hint=LOTTE
    )
    assert other["outcome"] == NEEDS_CLARIFICATION

    agreeing = build_project_preview(
        CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader(), merchant_hint=BETA
    )
    assert agreeing["outcome"] == READY


def test_basis_hash_detects_changed_authoritative_state():
    first = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader())
    again = build_project_preview(CREATE_EXAMPLES[2] + NO_PROCUREMENT, Reader())
    bumped = build_project_preview(
        CREATE_EXAMPLES[0] + NO_PROCUREMENT,
        Reader(merchants=[merchant(BETA, "BETA", "Beta Cinemas", version=2)]),
    )
    new_project = build_project_preview(
        CREATE_EXAMPLES[0] + NO_PROCUREMENT,
        Reader(projects=[project("Unrelated renovation")]),
    )

    assert first["basis_hash"] == again["basis_hash"]
    assert bumped["basis_hash"] != first["basis_hash"]
    assert new_project["basis_hash"] != first["basis_hash"]


@pytest.mark.parametrize(
    "request_text",
    (
        "Không tạo project, chỉ xem trước dự án mở rạp Beta Nguyễn Văn Cừ."
        + NO_PROCUREMENT,
        "Preview a cinema opening project for Beta Nguyễn Văn Cừ without "
        "procurement",
    ),
)
def test_preview_only_requests_get_the_same_non_executable_preview(request_text):
    preview = build_project_preview(request_text, Reader())

    assert preview["interpretation"]["write_requested"] is False
    assert preview["outcome"] == READY
    assert preview["executable"] is False
    assert preview["merchant"]["merchant_id"] == BETA


# ---------------------------------------------- No write, no authorization


def test_preview_carries_no_authorization_material():
    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader())

    assert preview["authorization"] is None
    assert preview["executable"] is False
    assert preview["requested_operation"]["status"] == "NOT_AUTHORIZED"
    text = repr(preview).lower()
    for marker in ("scope_hash", "confirmation_hash", "reservation", "token"):
        assert marker not in text


def test_preview_uses_only_read_apis():
    reader = Reader()
    build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, reader)

    assert set(reader.calls) == {
        "list_merchants", "list_projects", "get_workflow_template",
    }


def test_preview_is_a_read_command_and_its_operation_is_not_runnable_by_agents():
    assert "project preview" in READ_COMMANDS
    prepared = prepare_agent_cli_argv(
        ["project", "preview", "--request", CREATE_EXAMPLES[0]]
    )
    assert prepared[:2] == ("--database", "runtime")

    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader())
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv(preview["requested_operation"]["argv"])


def test_preview_in_run_state_records_no_execute_dispatch():
    preview = build_project_preview(CREATE_EXAMPLES[0] + NO_PROCUREMENT, Reader())
    state = {
        "run_id": "run-1",
        "operations": ["merchant_execute"],
        "merchant_scope": None,
        "confirmed": True,
        "project_preview": preview,
        "requested_operation": preview["requested_operation"],
    }

    assert policy_gate._record_merchant_execute_dispatch(
        state, "lead", "merchant-manager", "merchant-manager"
    ) is None
    assert "merchant_dispatch" not in state
    assert "merchant_dispatch_spent" not in state


def test_runtime_direct_execute_remains_disabled():
    assert merchant_direct_handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    assert project_preview.READY == "READY_FOR_CONFIRMATION"
