"""Claude Code subprocess provider.

Launches the ``claude`` CLI as a child process, feeds the prompt through
stdin, and returns the full text response. When ``stream`` is True the output
is echoed to the terminal incrementally, as the model produces it (like the
Claude Code CLI), rather than all at once when the process exits.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional
from threading import Lock


class ClaudeError(RuntimeError):
    """Raised when the Claude Code CLI cannot start or exits non-zero."""


def run_claude(
    prompt: str,
    tools: List[str],
    permission_mode: str = "default",
    allowed_tools: Optional[List[str]] = None,
    working_directory: Optional[str] = None,
    stream: bool = True,
    output_line_handler: Optional[Callable[[str], None]] = None,
) -> str:
    """Run the ``claude`` CLI and return its full text response.

    When ``stream`` is True the child's stdout is echoed live to this process's
    terminal as it arrives. If ``output_line_handler`` is provided, each line is
    passed to it for custom processing (e.g. prefixing with agent ID) before being
    echoed to stdout. Without a handler, output goes directly to sys.stdout.
    """
    allowed_tools = allowed_tools or []

    args = [
        "claude",
        "--print",
        "--tools",
        ",".join(tools),
        "--permission-mode",
        permission_mode,
        "--output-format",
        "text",
    ]

    if allowed_tools:
        args.append("--allowedTools")
        args.extend(allowed_tools)

    if stream:
        print("\nStarting Claude...\n", flush=True)

    max_retries = 5
    last_error = None

    for attempt in range(max_retries):
        try:
            process = subprocess.Popen(
                args,
                cwd=working_directory or None,
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as error:  # e.g. claude not on PATH
            last_error = error
            if attempt < max_retries - 1:
                backoff_time = 2 ** attempt
                time.sleep(backoff_time)
                continue
            else:
                raise ClaudeError(f"Could not start Claude Code: {error}") from error

        try:
            # Send the prompt, then close stdin so the CLI starts producing output.
            try:
                if process.stdin is not None:
                    process.stdin.write(prompt)
                    process.stdin.close()
            except BrokenPipeError:
                pass

            # Drain stderr on a background thread so a full stderr pipe can never
            # deadlock us while we read stdout.
            stderr_chunks: List[str] = []
            stderr_lock = Lock()

            def _drain_stderr() -> None:
                assert process.stderr is not None
                while True:
                    chunk = process.stderr.read(4096)
                    if not chunk:
                        break
                    with stderr_lock:
                        stderr_chunks.append(chunk)
                    if stream:
                        sys.stderr.write(chunk)
                        sys.stderr.flush()

            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()

            # Read stdout in chunks for character-by-character streaming.
            stdout_chunks: List[str] = []
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                stdout_chunks.append(chunk)
                if stream:
                    if output_line_handler:
                        output_line_handler(chunk)
                    else:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()

            process.wait()
            stderr_thread.join()

            stdout = "".join(stdout_chunks)
            with stderr_lock:
                stderr = "".join(stderr_chunks)

            if process.returncode != 0:
                raise ClaudeError(
                    f"Claude Code exited with code {process.returncode}\n{stderr}"
                )

            return stdout

        except ClaudeError as error:
            last_error = error
            if attempt < max_retries - 1:
                # Exponential backoff: 2^attempt seconds
                backoff_time = 2 ** attempt
                time.sleep(backoff_time)
            else:
                raise
