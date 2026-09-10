"""Tests for Merchant activation CLI commands."""

from __future__ import annotations

import argparse

import pytest

from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    build_write_payload,
)


class TestMerchantActivateArgumentParser:
    """Test CLI argument parsing for merchant activate."""

    def test_merchant_activate_parser_accepts_valid_args(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate",
                "--merchant-id",
                "550e8400-e29b-41d4-a716-446655440000",
                "--expected-version",
                "1",
                "--reason",
                "Merchant onboarding complete",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        assert args.resource == "merchant"
        assert args.action == "activate"
        assert args.merchant_id == "550e8400-e29b-41d4-a716-446655440000"
        assert args.expected_version == 1
        assert args.reason == "Merchant onboarding complete"
        assert args.triggered_by == "00000000-0000-0000-0000-000000000099"
        assert args.mode == "PROPOSE"

    def test_merchant_activate_parser_makes_required_fields_mandatory(self):
        parser = build_argument_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "merchant",
                    "activate",
                    "--merchant-id",
                    "550e8400-e29b-41d4-a716-446655440000",
                    # Missing expected-version, reason, mode
                ]
            )

    def test_merchant_activate_parser_accepts_optional_triggered_by(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate",
                "--merchant-id",
                "550e8400-e29b-41d4-a716-446655440000",
                "--expected-version",
                "1",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        assert args.triggered_by == "00000000-0000-0000-0000-000000000099"

    def test_merchant_activate_parser_supports_apply_mode(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate",
                "--merchant-id",
                "550e8400-e29b-41d4-a716-446655440000",
                "--expected-version",
                "1",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--apply",
                "--proposal-hash",
                "b8c414e02774a94ad28672b8d1c95341189815785f17f2988b502299821d4832",
            ]
        )

        assert args.mode == "APPLY"
        assert args.proposal_hash == (
            "b8c414e02774a94ad28672b8d1c95341189815785f17f2988b502299821d4832"
        )

    def test_merchant_activate_parser_rejects_invalid_version(self):
        parser = build_argument_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "merchant",
                    "activate",
                    "--merchant-id",
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--expected-version",
                    "not-a-number",
                    "--reason",
                    "Test",
                    "--propose",
                ]
            )


class TestMerchantActivateAllArgumentParser:
    """Test CLI argument parsing for merchant activate-all."""

    def test_merchant_activate_all_parser_accepts_valid_args(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "ONBOARDING",
                "--expected-count",
                "22",
                "--reason",
                "Existing merchants imported during runtime initialization",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        assert args.resource == "merchant"
        assert args.action == "activate-all"
        assert args.from_status == "ONBOARDING"
        assert args.expected_count == 22
        assert args.reason == "Existing merchants imported during runtime initialization"
        assert args.triggered_by == "00000000-0000-0000-0000-000000000099"
        assert args.mode == "PROPOSE"

    def test_merchant_activate_all_parser_normalizes_status_to_uppercase(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "onboarding",
                "--expected-count",
                "1",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        assert args.from_status == "ONBOARDING"

    def test_merchant_activate_all_parser_accepts_valid_statuses(self):
        parser = build_argument_parser()

        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "ONBOARDING",
                "--expected-count",
                "1",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )
        assert args.from_status == "ONBOARDING"

    def test_merchant_activate_all_parser_rejects_invalid_status(self):
        parser = build_argument_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "merchant",
                    "activate-all",
                    "--from-status",
                    "INACTIVE",  # Not allowed (only ONBOARDING)
                    "--expected-count",
                    "1",
                    "--reason",
                    "Test",
                    "--triggered-by",
                    "00000000-0000-0000-0000-000000000099",
                    "--propose",
                ]
            )

    def test_merchant_activate_all_parser_makes_required_fields_mandatory(self):
        parser = build_argument_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "merchant",
                    "activate-all",
                    "--from-status",
                    "ONBOARDING",
                    # Missing expected-count, reason, mode
                ]
            )

    def test_merchant_activate_all_parser_accepts_triggered_by(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "ONBOARDING",
                "--expected-count",
                "22",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        assert args.triggered_by == "00000000-0000-0000-0000-000000000099"

    def test_merchant_activate_all_parser_rejects_non_positive_count(self):
        parser = build_argument_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "merchant",
                    "activate-all",
                    "--from-status",
                    "ONBOARDING",
                    "--expected-count",
                    "0",  # Must be >= 1
                    "--reason",
                    "Test",
                    "--propose",
                ]
            )


class TestMerchantActivatePayloadBuilder:
    """Test payload building for merchant activate commands."""

    def test_merchant_activate_payload_includes_required_fields(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate",
                "--merchant-id",
                "550e8400-e29b-41d4-a716-446655440000",
                "--expected-version",
                "1",
                "--reason",
                "Test reason",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        payload = build_write_payload(args, "merchant activate")

        assert payload["merchant_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert payload["expected_version"] == 1
        assert payload["reason"] == "Test reason"
        assert "triggered_by" in payload
        assert payload["triggered_by"] == "00000000-0000-0000-0000-000000000099"

    def test_merchant_activate_payload_includes_triggered_by_when_provided(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate",
                "--merchant-id",
                "550e8400-e29b-41d4-a716-446655440000",
                "--expected-version",
                "1",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        payload = build_write_payload(args, "merchant activate")

        assert payload["triggered_by"] == "00000000-0000-0000-0000-000000000099"

    def test_merchant_activate_all_payload_includes_required_fields(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "ONBOARDING",
                "--expected-count",
                "22",
                "--reason",
                "Batch activation reason",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        payload = build_write_payload(args, "merchant activate-all")

        assert payload["from_status"] == "ONBOARDING"
        assert payload["expected_count"] == 22
        assert payload["reason"] == "Batch activation reason"
        assert payload["triggered_by"] == "00000000-0000-0000-0000-000000000099"

    def test_merchant_activate_all_payload_preserves_status_format(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "ONBOARDING",
                "--expected-count",
                "5",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        payload = build_write_payload(args, "merchant activate-all")

        assert payload["from_status"] == "ONBOARDING"

    def test_merchant_activate_all_payload_includes_triggered_by_when_provided(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "merchant",
                "activate-all",
                "--from-status",
                "ONBOARDING",
                "--expected-count",
                "22",
                "--reason",
                "Test",
                "--triggered-by",
                "00000000-0000-0000-0000-000000000099",
                "--propose",
            ]
        )

        payload = build_write_payload(args, "merchant activate-all")

        assert payload["triggered_by"] == "00000000-0000-0000-0000-000000000099"
