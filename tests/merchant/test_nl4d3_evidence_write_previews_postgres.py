"""CP12H.NL4D3 on the Merchant test database: write previews read only.

No fixture is written. Each preview runs through the real agent CLI against
the accepted NL4C2B acceptance Project (no revisions, approvals or
procurement records; no procurement required), and every table the preview
could touch must be byte-identical afterwards. Must run alone.
"""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.agent_cli import prepare_agent_cli_argv
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from tests.merchant.test_nl4c1_step_confirmation_postgres import pytestmark  # noqa: F401
from tests.merchant.test_nl4d2_evidence_discovery_postgres import counts

PROJECT_ID = "8dd4c68d-76a9-571b-ad08-a864d7fcf7a5"
NAMED = "Project Beta NL4C2B Step Acceptance"


@pytest.fixture(autouse=True)
def no_recording_operator(monkeypatch):
    """CP12H.NL4D4A: without a trusted operator no preview is confirmable, so
    these read-only assertions hold whatever the local configuration says."""

    monkeypatch.delenv("MERCHANT_OPERATOR_ID", raising=False)


@pytest.fixture
def repository():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    with repository.connection(read_only=True) as connection:
        row = connection.execute(
            "SELECT count(*) AS n FROM merchant_ops.projects WHERE id = %s", (PROJECT_ID,)
        ).fetchone()
    if row["n"] != 1:
        pytest.skip("the NL4C2B acceptance Project is not in this test database")
    return repository


def run(repository, text):
    argv = prepare_agent_cli_argv(["evidence", "preview", "--request", text, "--test-database"])
    args = merchant_cli.build_argument_parser().parse_args(argv)
    result = merchant_cli.dispatch_read_command(
        args, MerchantReadCommands(MerchantReadRepository(repository)))
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("text,outcome,code", [
    (f"Ghi nhận Purchase Request PR-001 cho {NAMED} trên database test", "PREVIEW_VALID", None),
    (f"Ghi nhận Purchase Order PO-001 cho {NAMED}", "BLOCKED", "ProcurementDependencyError"),
    (f"Ghi nhận Payment Request PAY-001 cho {NAMED}", "BLOCKED", "ProcurementDependencyError"),
    (f"Legal đã phê duyệt revision mới nhất của {NAMED}.", "BLOCKED",
     "MISSING_DOCUMENT_REVISION"),
    # CP12H.MASTER: metadata-only revisions take no content hash.
    (f"Upload a new CONTRACT revision for {NAMED}", "PREVIEW_VALID", None),
    (f"Upload a new CONTRACT revision for {NAMED}, content hash sha256:nl4d3", "BLOCKED",
     "CONTENT_HASH_NOT_ACCEPTED"),
    (f"Thêm revision tài liệu cho {NAMED}", "NEEDS_CLARIFICATION", None),
])
def test_a_preview_on_the_test_database_reads_only(repository, text, outcome, code):
    before = counts(repository)
    result = run(repository, text)
    after = counts(repository)

    assert after == before
    assert result["mode"] == "EVIDENCE_WRITE_PREVIEW"
    assert result["database_target"] == "test"
    assert result["project_id"] == PROJECT_ID
    assert result["read_only"] is True and result["executable"] is False
    assert result["confirmation_available"] is False and result["requested_operation"] is None
    assert result["outcome"] == outcome
    if code:
        assert result["domain_validation"]["error"]["code"] == code
    assert "sha256:nl4d3" not in json.dumps(result)


def test_a_new_revision_would_be_the_first(repository):
    result = run(repository, f"Upload a new CONTRACT revision for {NAMED}")

    assert result["domain_validation"]["plan"]["revision_number"] == 1
    assert result["domain_validation"]["plan"]["previous_revision_id"] is None
