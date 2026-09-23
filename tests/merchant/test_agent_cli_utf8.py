"""UTF-8 boundary tests for the Merchant operational agent CLI."""

from __future__ import annotations

import io
import sys

from claude.agents.tools.merchant import agent_cli


UNICODE_TEXT = (
    "BETA PHÚ MỸ — "
    "TRUNG TÂM CHIẾU PHIM"
)


def test_main_reconfigures_windows_style_streams_to_utf8(
    monkeypatch,
):
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()

    stdout = io.TextIOWrapper(
        stdout_bytes,
        encoding="cp1252",
        errors="strict",
        newline="\n",
        write_through=True,
    )

    stderr = io.TextIOWrapper(
        stderr_bytes,
        encoding="cp1252",
        errors="strict",
        newline="\n",
        write_through=True,
    )

    monkeypatch.setattr(
        agent_cli.sys,
        "stdout",
        stdout,
    )

    monkeypatch.setattr(
        agent_cli.sys,
        "stderr",
        stderr,
    )

    def fake_invoke(
        arguments,
    ):
        assert tuple(
            arguments
        ) == (
            "merchant",
            "list",
        )

        print(
            UNICODE_TEXT
        )

        print(
            UNICODE_TEXT,
            file=sys.stderr,
        )

        return 0

    monkeypatch.setattr(
        agent_cli,
        "invoke_agent_cli",
        fake_invoke,
    )

    exit_code = agent_cli.main(
        (
            "merchant",
            "list",
        )
    )

    stdout.flush()
    stderr.flush()

    assert exit_code == 0

    assert (
        stdout.encoding
        .lower()
        .replace(
            "_",
            "-",
        )
        == "utf-8"
    )

    assert (
        stderr.encoding
        .lower()
        .replace(
            "_",
            "-",
        )
        == "utf-8"
    )

    assert (
        stdout_bytes
        .getvalue()
        .decode(
            "utf-8"
        )
        == f"{UNICODE_TEXT}\n"
    )

    assert (
        stderr_bytes
        .getvalue()
        .decode(
            "utf-8"
        )
        == f"{UNICODE_TEXT}\n"
    )


def test_utf8_configuration_leaves_stringio_usable(
    monkeypatch,
):
    stdout = io.StringIO()
    stderr = io.StringIO()

    monkeypatch.setattr(
        agent_cli.sys,
        "stdout",
        stdout,
    )

    monkeypatch.setattr(
        agent_cli.sys,
        "stderr",
        stderr,
    )

    def fake_invoke(
        arguments,
    ):
        print(
            UNICODE_TEXT
        )

        return 0

    monkeypatch.setattr(
        agent_cli,
        "invoke_agent_cli",
        fake_invoke,
    )

    exit_code = agent_cli.main(
        (
            "merchant",
            "list",
        )
    )

    assert exit_code == 0
    assert stdout.getvalue() == (
        f"{UNICODE_TEXT}\n"
    )
    assert stderr.getvalue() == ""