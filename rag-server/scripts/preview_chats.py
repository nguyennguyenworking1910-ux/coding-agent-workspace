#!/usr/bin/env python3
"""Preview Claude Code chat transcripts without ingestion."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.ingestion.chat_scanner import ChatScanner, ChatScanError
from app.ingestion.claude_transcript_loader import (
    ClaudeTranscriptLoader,
    TranscriptLoadError,
)
from app.ingestion.chunker import DocumentChunker

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> int:
    """Preview chat transcripts."""
    parser = argparse.ArgumentParser(description="Preview Claude Code transcripts")
    parser.add_argument("--root", type=str, default=".", help="Repository root")
    parser.add_argument(
        "--since-days", type=int, default=30, help="Include transcripts from last N days"
    )
    parser.add_argument("--session-id", type=str, help="Specific session to preview")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()

    root = Path(args.root).resolve()
    settings = Settings.from_env()

    # Resolve projects directory
    projects_dir = ChatScanner.resolve_projects_dir(
        os.getenv("RAG_CLAUDE_PROJECTS_DIR")
    )

    if not projects_dir.exists():
        print(f"ERROR: Projects directory not found: {projects_dir}", file=sys.stderr)
        return 1

    # Initialize
    try:
        scanner = ChatScanner(
            projects_dir,
            root,
            max_file_bytes=int(
                os.getenv("RAG_CHAT_MAX_FILE_BYTES", "52428800")
            ),
        )
    except ChatScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    loader = ClaudeTranscriptLoader(
        root,
        max_file_bytes=int(os.getenv("RAG_CHAT_MAX_FILE_BYTES", "52428800")),
        max_text_chars=int(os.getenv("RAG_CHAT_MAX_TEXT_CHARS", "2000000")),
        quiet_period_seconds=int(os.getenv("RAG_CHAT_QUIET_PERIOD_SECONDS", "60")),
        max_invalid_line_ratio=float(os.getenv("RAG_CHAT_MAX_INVALID_LINE_RATIO", "0.05")),
    )

    chunker = DocumentChunker()
    since_seconds = args.since_days * 86400

    # Scan and load
    discovered = 0
    loaded = 0
    skipped = 0
    skip_reasons = {}
    total_messages = 0
    user_messages = 0
    assistant_messages = 0
    total_redactions = 0
    parent_chunks = 0
    child_chunks = 0
    max_parent_chars = 0
    max_child_chars = 0
    sessions = []

    try:
        if args.session_id:
            scan_iter = scanner.scan(args.session_id)
        else:
            scan_iter = scanner.scan()

        for scanned in scan_iter:
            discovered += 1

            # Check age
            import time
            if time.time() - scanned.modified_time > since_seconds:
                skipped += 1
                skip_reasons["too_old"] = skip_reasons.get("too_old", 0) + 1
                continue

            try:
                doc = loader.load(scanned.file_path, scanned.session_id)
                loaded += 1

                # Chunk for statistics
                plan = chunker.chunk(doc)
                parent_chunks += len(plan.parents)
                child_chunks += len(plan.children)

                for parent in plan.parents:
                    max_parent_chars = max(max_parent_chars, len(parent.content))
                for child in plan.children:
                    max_child_chars = max(max_child_chars, len(child.content))

                # Accumulate stats
                msg_count = doc.metadata.get("message_count", 0)
                total_messages += msg_count
                user_messages += doc.metadata.get("user_message_count", 0)
                assistant_messages += doc.metadata.get("assistant_message_count", 0)
                total_redactions += doc.metadata.get("redaction_count", 0)

                # Add to sessions list (without message content)
                sessions.append({
                    "session_id": doc.metadata.get("session_id"),
                    "message_count": msg_count,
                    "user_messages": doc.metadata.get("user_message_count", 0),
                    "assistant_messages": doc.metadata.get("assistant_message_count", 0),
                    "redactions": doc.metadata.get("redaction_count", 0),
                })

            except TranscriptLoadError as e:
                skipped += 1
                skip_reasons[e.reason] = skip_reasons.get(e.reason, 0) + 1
                continue

    except ChatScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Check if explicitly requested session was found
    if args.session_id and loaded == 0:
        print(f"ERROR: Session {args.session_id} not found or could not be loaded", file=sys.stderr)
        return 1

    # Output
    results = {
        "discovered_transcripts": discovered,
        "project_transcripts": discovered,
        "loaded_sessions": loaded,
        "skipped_sessions": skipped,
        "skip_reasons": skip_reasons,
        "total_messages": total_messages,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "redaction_count": total_redactions,
        "parent_chunks": parent_chunks,
        "child_chunks": child_chunks,
        "max_parent_chars": max_parent_chars,
        "max_child_chars": max_child_chars,
        "sessions": sessions,
    }

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("\nClaude Code Chat Preview")
        print("=" * 50)
        print(f"Discovered transcripts:  {discovered}")
        print(f"Loaded sessions:        {loaded}")
        print(f"Skipped sessions:       {skipped}")

        if skip_reasons:
            print(f"\nSkip reasons:")
            for reason, count in skip_reasons.items():
                print(f"  {reason}: {count}")

        print(f"\nMessages:")
        print(f"  Total:      {total_messages}")
        print(f"  User:       {user_messages}")
        print(f"  Assistant:  {assistant_messages}")

        print(f"\nRedactions: {total_redactions}")

        print(f"\nChunking:")
        print(f"  Parents:    {parent_chunks}")
        print(f"  Children:   {child_chunks}")
        print(f"  Max parent: {max_parent_chars}")
        print(f"  Max child:  {max_child_chars}")

    print("\nSTEP6D_CHAT_PREVIEW_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
