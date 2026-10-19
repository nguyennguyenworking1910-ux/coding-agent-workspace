from pathlib import Path
import sys

sys.path.insert(
    0, str(Path(".claude/system").resolve())
)

from intent_parser import IntentParser


def classify(request):
    return IntentParser._detect_local_merchant_operation(
        request.lower()
    )


def test_galaxy_read_only_negated_actions():
    request = (
        "Perform a strictly read-only Merchant audit for merchant code GALAXY. "
        "This is a merchant_read operation, NOT merchant_propose or merchant_apply. "
        "Resolve GALAXY and inspect integration readiness. "
        "Do not create proposals, activate merchants, create projects, "
        "access .env, run SQL, or modify files."
    )
    assert classify(request) == "merchant_read"


def test_positive_activation_proposal_remains_propose():
    request = (
        "Prepare a Merchant activation proposal for GALAXY. "
        "Do not apply or execute the proposal."
    )
    assert classify(request) == "merchant_propose"


def test_confirmed_activation_remains_apply():
    request = (
        "Apply the previously confirmed Merchant activation proposal "
        "for GALAXY."
    )
    assert classify(request) == "merchant_apply"
