"""CP12H.NL4C2B-FIX: live Step resolution and merchant-manager command quoting.

Live failures (coding_agent_merchant_test, Project "Beta NL4C2B Step
Acceptance"): both previews below resolved the Project and IN_PROGRESS but
returned ``step_reference = null``. The word "Step" inside the Project title
was read as a second step reference, and two references fail closed.

Separately, the Bash policy rejected ``--request "... \\"Draft or renew
document\\" ..."``: an escaped double quote inside double quotes. Bash and
POSIX shlex agree on ``\\"`` and ``\\\\``, so those two escapes are now
literal; every other backslash, expansion and operator stays rejected.
"""

from __future__ import annotations

import json
import uuid

import pytest

from claude.agents.tools.merchant.project_nl import (
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.step_preview import CLARIFY, READY
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks.policy_gate import (
    exact_merchant_manager_command,
    merchant_runtime_bypass_decision,
)
from tests.merchant.test_nl4b_step_preview import (  # noqa: F401 (fixtures)
    BETA,
    LEAD,
    StepReader,
    edge,
    capture,
    isolated,
    preview,
    project,
    step,
    step_run,
)

ACC = "Project Beta NL4C2B Step Acceptance"
LIVE_1 = f"Cập nhật bước 1 của {ACC} thành đang thực hiện trên database test"
LIVE_2 = (f'Cập nhật bước "Draft or renew document" của {ACC} '
          "thành đang thực hiện trên database test")
P_ACC = "dddddddd-0000-4000-8000-000000000001"
P_ACC_TWO = "dddddddd-0000-4000-8000-000000000002"
P_UNICODE = "dddddddd-0000-4000-8000-000000000003"
CLI = "python .claude/agents/tools/merchant/agent_cli.py"

STEPS = [
    step(1, "Draft or renew document", "READY"),
    step(2, "Legal review", "PENDING"),
    step(3, "Accounting review", "PENDING"),
    step(4, "Send reviewed revision to Partner", "PENDING"),
    step(5, "Soạn thảo phụ lục hợp đồng", "PENDING"),
    step(6, "Step review", "PENDING"),            # a title that itself says "Step"
]


class AcceptanceReader(StepReader):
    def __init__(self, steps=STEPS):
        super().__init__(steps=steps)
        self.projects += [
            project(P_ACC, "Beta NL4C2B Step Acceptance"),
            project(P_ACC_TWO, "Beta NL4C2B Step Acceptance Two"),   # similar title
            project(P_UNICODE, "Beta Nguyễn Văn Cừ Step Acceptance"),
        ]

    def get_project_detail(self, project_id):
        detail = super().get_project_detail(project_id)
        # Step 1 leads every other step (the fixture's own graph).
        detail["dependencies"] = [edge(1, s["sequence_number"]) for s in self.steps
                                  if s["sequence_number"] != 1]
        return detail


def ask(text, reader=None):
    return preview(text, reader or AcceptanceReader())


def chosen(result):
    assert result["outcome"] == READY, (result["missing"], result["clarifications"])
    return result["project"]["project_id"], result["step"]["sequence"]


# ---------------------------------------------------------------- parser


@pytest.mark.parametrize(
    "text,reference",
    [
        (LIVE_1, "1"),
        (LIVE_2, "Draft or renew document"),
        (f"Bắt đầu bước 1 của {ACC} của Merchant Beta Cinemas trên database test", "1"),
        (f"Cập nhật bước số 1 của {ACC} thành đang thực hiện", "1"),
        (f"Mark step 1 of {ACC} as in progress", "1"),
        (f"Mark Step 01 of {ACC} as in progress", "01"),
        (f"Mark step number 1 of {ACC} as in progress", "1"),
        (f"Cập nhật bước Draft or renew document của {ACC} thành đang thực hiện",
         "Draft or renew document"),
        (f"Mark the Draft or renew document step of {ACC} as in progress",
         "Draft or renew document"),
        (f"Đánh dấu Draft or renew document của {ACC} là đang thực hiện",
         "Draft or renew document"),
        (f"Cập nhật bước Soạn thảo phụ lục hợp đồng của {ACC} thành đang thực hiện",
         "Soạn thảo phụ lục hợp đồng"),
        (f"Cập nhật bước Step review của {ACC} thành đang thực hiện", "Step review"),
        ("Cập nhật bước 1 của Project Beta Nguyễn Văn Cừ Step Acceptance thành đang thực hiện", "1"),
    ],
)
def test_step_reference_survives_a_project_title_containing_step(text, reference):
    result = interpret_project_request(text)

    assert result.kind == STEP_UPDATE
    assert result.step_reference == reference
    assert result.target_status == "IN_PROGRESS"
    assert "Step Acceptance" in result.project_phrase


@pytest.mark.parametrize(
    "text",
    [
        f"Cập nhật bước 1 và bước 2 của {ACC} thành đang thực hiện",   # two steps
        f"Cập nhật của {ACC} thành đang thực hiện",                      # no step
        f"Đánh dấu bước của {ACC} là hoàn thành",                        # noun, no name
    ],
)
def test_no_single_step_is_never_guessed(text):
    assert interpret_project_request(text).step_reference is None


def test_status_question_stays_a_read():
    result = interpret_project_request(f"{ACC} hiện tại đến bước nào?")
    assert result.kind == PROJECT_STATUS and result.step_reference is None


# -------------------------------------------- preview against stored steps


@pytest.mark.parametrize("text", [
    LIVE_1, LIVE_2,
    f"Mark Step 01 of {ACC} as in progress",
    f"Đánh dấu Draft or renew document của {ACC} là đang thực hiện",
    f"Cập nhật bước draft OR RENEW document của {ACC} thành đang thực hiện",   # case
])
def test_live_requests_resolve_the_persisted_step(text):
    assert chosen(ask(text)) == (P_ACC, 1)


def test_a_title_cut_at_a_stop_word_resolves_to_the_whole_stored_title():
    # The parser ends the name at "to"; the stored title the user wrote wins.
    text = f"Cập nhật bước Send reviewed revision to Partner của {ACC} thành đang thực hiện"
    assert interpret_project_request(text).step_reference == "Send reviewed revision"
    reader = AcceptanceReader([dict(s, status="READY") if s["sequence_number"] == 4 else
                               dict(s, status="COMPLETED") for s in STEPS])

    assert chosen(ask(text, reader)) == (P_ACC, 4)


def test_unicode_project_with_step_in_its_title_resolves():
    text = "Cập nhật bước 1 của Project Beta Nguyễn Văn Cừ Step Acceptance thành đang thực hiện"
    assert chosen(ask(text)) == (P_UNICODE, 1)


@pytest.mark.parametrize(
    "text,field",
    [
        (f"Cập nhật bước 99 của {ACC} thành đang thực hiện", "step"),           # invalid number
        (f"Cập nhật bước Kickoff meeting của {ACC} thành đang thực hiện", "step"),  # missing
        (f"Cập nhật bước review của {ACC} thành đang thực hiện", "step"),        # partial: ambiguous
        (f"Cập nhật bước 1 và bước 2 của {ACC} thành đang thực hiện", "step"),
        ("Cập nhật bước 1 của Project Beta NL4C2B thành đang thực hiện", "project"),  # 3 similar
    ],
)
def test_invalid_or_ambiguous_references_fail_closed(text, field):
    result = ask(text)

    assert result["outcome"] == CLARIFY and field in result["missing"]
    assert result["requested_operation"] is None


def test_duplicate_step_titles_are_ambiguous():
    reader = AcceptanceReader(STEPS + [step(7, "Draft or renew document", "PENDING")])
    result = ask(LIVE_2, reader)

    assert result["outcome"] == CLARIFY and result["requested_operation"] is None
    assert {c["sequence"] for c in result["candidates"]} == {1, 7}


def test_similar_project_titles_bind_only_the_exact_one():
    two = f"Cập nhật bước 1 của {ACC} Two thành đang thực hiện"
    assert chosen(ask(two)) == (P_ACC_TWO, 1)
    assert chosen(ask(LIVE_1)) == (P_ACC, 1)


def test_an_unresolved_step_never_creates_a_pending_confirmation(step_run):
    text = f"Cập nhật bước 99 của {ACC} thành đang thực hiện trên database test"
    result, stdout = step_run(text, AcceptanceReader())
    assert result["outcome"] == CLARIFY

    capture(f'{CLI} step preview --request "{text}" --test-database', stdout)

    assert pending.load_records(LEAD, pending.STEP_KIND) == []


def test_the_live_quoted_title_capture_records_one_pending_step(step_run):
    result, stdout = step_run(LIVE_2, AcceptanceReader())
    assert result["outcome"] == READY
    escaped = LIVE_2.replace('"', '\\"')

    assert capture(f'{CLI} step preview --request "{escaped}" --test-database', stdout)

    (record,) = pending.load_records(LEAD, pending.STEP_KIND)
    assert record["step_id"] == str(uuid.UUID(int=1))
    assert record["operation"]["project_id"] == P_ACC


# ------------------------------------------------------------- quoting


BLOCKED_LIVE = [
    # Both commands the live session's PreToolUse(Bash) hook denied.
    f'{CLI} step preview --request "Cập nhật bước \\"Draft or renew document\\" của '
    f'{ACC} thành đang thực hiện trên database test" --test-database',
    f'{CLI} completeness check --command "project create" --argv-json '
    '"[\\"project\\",\\"create\\",\\"--title\\",\\"Beta NL4C2B Step Acceptance\\"]"',
]


def test_the_live_escaped_quote_commands_parse_to_the_intended_argv():
    request = exact_merchant_manager_command(BLOCKED_LIVE[0])
    assert request is not None and request[2:4] == ("step", "preview")
    assert request[5] == LIVE_2                                  # the user's exact words

    single = exact_merchant_manager_command(
        f"{CLI} step preview --request '{LIVE_2}' --test-database")
    assert single == request                                     # same argv either way

    check = exact_merchant_manager_command(BLOCKED_LIVE[1])
    assert json.loads(check[-1]) == ["project", "create", "--title", "Beta NL4C2B Step Acceptance"]


@pytest.mark.parametrize("command", BLOCKED_LIVE)
def test_the_policy_gate_allows_them_for_merchant_manager(command):
    payload = {"agent_type": "merchant-manager", "tool_name": "Bash",
               "tool_input": {"command": command}}
    assert merchant_runtime_bypass_decision(payload) is None


@pytest.mark.parametrize(
    "command",
    [
        f'{CLI} step preview --request "a $(rm -rf x) b" --test-database',
        f'{CLI} step preview --request "a \\$(id) b" --test-database',      # escaped $
        f'{CLI} step preview --request "a `id` b" --test-database',
        f'{CLI} step preview --request "a \\`id\\` b" --test-database',
        f'{CLI} step preview --request "a ${{HOME}} b" --test-database',
        f'{CLI} step preview --request "a !! b" --test-database',
        f'{CLI} step preview --request "a \\n b" --test-database',          # other escape
        f'{CLI} step preview --request "C:\\Users\\x" --test-database',     # Windows path
        f'{CLI} step preview --request "a" --test-database; id',
        f'{CLI} step preview --request "a" --test-database && id',
        f'{CLI} step preview --request "a" | id',
        f'{CLI} step preview --request "a" > out.txt',
        f'{CLI} step preview --request "a\\" --test-database',             # never closed
        f'{CLI} step preview --request "a" \\" --test-database',            # escape outside quotes
        f'{CLI} step preview --request \'a\nb\' --test-database',
        f'FOO=1 {CLI} step preview --request "a"',
        f'python -c "import os" .claude/agents/tools/merchant/agent_cli.py step preview',
        'python other.py --request "a \\"b\\""',
    ],
)
def test_injection_and_other_escapes_stay_rejected(command):
    assert exact_merchant_manager_command(command) is None
    payload = {"agent_type": "merchant-manager", "tool_name": "Bash",
               "tool_input": {"command": command}}
    assert merchant_runtime_bypass_decision(payload)["hookSpecificOutput"][
        "permissionDecision"] == "deny"


def test_unicode_and_single_quotes_stay_literal():
    tokens = exact_merchant_manager_command(
        f"{CLI} step preview --request 'Bắt đầu bước 1 của Project \"Cừ\" $HOME' --test-database")
    assert tokens[5] == 'Bắt đầu bước 1 của Project "Cừ" $HOME'   # no expansion
