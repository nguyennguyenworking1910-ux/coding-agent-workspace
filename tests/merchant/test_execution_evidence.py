import uuid

import pytest

from claude.hooks.merchant_execution_evidence import (
    verify_committed_merchant_create,
)


KEY = "merchant-direct:v1:test"
HASH = "a" * 64
MERCHANT_ID = str(uuid.uuid4())


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        pass

    def fetchone(self):
        return next(self.rows)


class Connection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return Cursor(self.rows)


class Repository:
    def __init__(self, rows):
        self.rows = rows
        self.read_only = None

    def connection(self, *, read_only=False):
        self.read_only = read_only
        return Connection(self.rows)


def valid_rows():
    return [
        {
            "payload_hash": HASH,
            "result": {
                "success": True,
                "merchant_id": MERCHANT_ID,
            },
        },
        {"n": 1},
        {"n": 1},
    ]


def test_committed_evidence_accepted():
    repo = Repository(valid_rows())

    result = verify_committed_merchant_create(
        repo,
        operation_key=KEY,
        payload_hash=HASH,
    )

    assert result["verified"] is True
    assert result["merchant_id"] == MERCHANT_ID
    assert repo.read_only is True


@pytest.mark.parametrize(
    "rows",
    [
        [None],
        [
            {
                "payload_hash": "b" * 64,
                "result": {
                    "success": True,
                    "merchant_id": MERCHANT_ID,
                },
            },
        ],
        [
            {
                "payload_hash": HASH,
                "result": None,
            },
        ],
        [
            {
                "payload_hash": HASH,
                "result": {
                    "success": False,
                    "merchant_id": MERCHANT_ID,
                },
            },
        ],
        [
            {
                "payload_hash": HASH,
                "result": {
                    "success": True,
                    "merchant_id": MERCHANT_ID,
                },
            },
            {"n": 0},
        ],
        [
            {
                "payload_hash": HASH,
                "result": {
                    "success": True,
                    "merchant_id": MERCHANT_ID,
                },
            },
            {"n": 1},
            {"n": 0},
        ],
    ],
)
def test_invalid_evidence_rejected(rows):
    repo = Repository(rows)

    assert verify_committed_merchant_create(
        repo,
        operation_key=KEY,
        payload_hash=HASH,
    ) is None
