#!/usr/bin/env python3
"""Ingest Claude Code chats with privacy-safe dry-run planning or production apply."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings, ConfigurationError
from app.database import create_pool
from app.ingestion.chat_scanner import ChatScanner, ChatScanError
from app.ingestion.claude_transcript_loader import (
    ClaudeTranscriptLoader,
    TranscriptLoadError,
)
from app.ingestion.chunker import DocumentChunker
from app.ingestion.embedding_client import HttpEmbeddingClient
from app.ingestion.service import IngestionService

# Configure logging - only to stderr
logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Ingest chat transcripts in dry-run or apply mode."""
    parser = argparse.ArgumentParser(
        description="Ingest Claude Code transcripts"
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="Repository root directory (default: current dir)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="Include transcripts from last N days (default: 30)",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Specific session ID to ingest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making database changes",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply ingestion to database",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Validate that exactly one of --dry-run or --apply is specified
    if args.dry_run and args.apply:
        print(
            "ERROR: --dry-run and --apply are mutually exclusive",
            file=sys.stderr,
        )
        return 1

    if not args.dry_run and not args.apply:
        print(
            "ERROR: one of --dry-run or --apply is required",
            file=sys.stderr,
        )
        return 1

    # Validate --since-days
    if args.since_days < 0:
        print(
            f"ERROR: --since-days must be non-negative (got {args.since_days})",
            file=sys.stderr,
        )
        return 1

    # Resolve root
    root = Path(args.root).resolve()
    start_time = time.time()

    # Initialize scanner and loader
    projects_dir = ChatScanner.resolve_projects_dir()

    try:
        scanner = ChatScanner(projects_dir, root)
    except ChatScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    loader = ClaudeTranscriptLoader(
        root,
        quiet_period_seconds=int(os.getenv("RAG_CHAT_QUIET_PERIOD_SECONDS", "60")),
    )
    chunker = DocumentChunker()

    # Collect results
    discovered_transcripts = 0
    planned_sources = 0
    skipped_sessions = 0
    failed_sessions = 0
    skip_reasons: dict[str, int] = {}
    failed_reasons: dict[str, int] = {}

    total_messages = 0
    user_messages = 0
    assistant_messages = 0
    total_redactions = 0

    parent_chunks = 0
    child_chunks = 0

    sessions = []
    loaded_documents = []
    since_seconds = args.since_days * 86400

    # PHASE 1: Scan and load transcripts (both dry-run and apply)
    try:
        # Determine if we're scanning specific session or all
        if args.session_id:
            scan_iter = scanner.scan(args.session_id)
        else:
            scan_iter = scanner.scan()

        for scanned in scan_iter:
            discovered_transcripts += 1

            # Check age
            if time.time() - scanned.modified_time > since_seconds:
                skipped_sessions += 1
                skip_reasons["too_old"] = skip_reasons.get("too_old", 0) + 1
                continue

            # Load transcript
            try:
                doc = loader.load(scanned.file_path, scanned.session_id)
                planned_sources += 1
                loaded_documents.append(doc)

                # Chunk the transcript
                plan = chunker.chunk(doc)
                parent_chunks += len(plan.parents)
                child_chunks += len(plan.children)

                # Accumulate message stats
                msg_count = doc.metadata.get("message_count", 0)
                total_messages += msg_count
                user_msg_count = doc.metadata.get("user_message_count", 0)
                user_messages += user_msg_count
                asst_msg_count = doc.metadata.get("assistant_message_count", 0)
                assistant_messages += asst_msg_count
                total_redactions += doc.metadata.get("redaction_count", 0)

                # Add to sessions list (privacy-safe data only)
                sessions.append({
                    "session_id": scanned.session_id,
                    "message_count": msg_count,
                    "user_messages": user_msg_count,
                    "assistant_messages": asst_msg_count,
                    "redactions": doc.metadata.get("redaction_count", 0),
                    "parent_chunks": len(plan.parents),
                    "child_chunks": len(plan.children),
                })

            except TranscriptLoadError as e:
                failed_sessions += 1
                failed_reasons[e.reason] = failed_reasons.get(e.reason, 0) + 1
                # If explicit session requested and it failed, return error
                if args.session_id:
                    reason_msg = e.reason if e.reason else "unknown error"
                    print(
                        f"ERROR: Session {args.session_id} could not be loaded ({reason_msg})",
                        file=sys.stderr,
                    )
                    return 1
                continue

    except ChatScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("Unexpected error during transcript loading")
        print(f"ERROR: Unexpected error during transcript processing", file=sys.stderr)
        return 1

    # Check if explicitly requested session was not discovered
    if args.session_id and discovered_transcripts == 0:
        print(f"ERROR: Session {args.session_id} not found", file=sys.stderr)
        return 1

    # Merge skip and fail reasons for reporting
    all_skip_reasons = {**skip_reasons, **failed_reasons}

    # Calculate elapsed time
    elapsed_ms = int((time.time() - start_time) * 1000)

    # PHASE 2: Handle --dry-run mode (no infrastructure initialization)
    if args.dry_run:
        results = {
            "mode": "dry_run",
            "discovered_transcripts": discovered_transcripts,
            "project_transcripts": discovered_transcripts,
            "planned_sources": planned_sources,
            "skipped_sessions": skipped_sessions,
            "failed_sessions": failed_sessions,
            "skip_reasons": all_skip_reasons,
            "total_messages": total_messages,
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "redaction_count": total_redactions,
            "parent_chunks": parent_chunks,
            "child_chunks": child_chunks,
            "would_embed_children": child_chunks,
            "database_writes": 0,
            "embedding_requests": 0,
            "elapsed_ms": elapsed_ms,
            "sessions": sessions,
        }

        # Output dry-run results
        if args.json:
            print(json.dumps(results, indent=2))
            print("\nSTEP6D_CHAT_DRY_RUN_OK", file=sys.stderr)
        else:
            print("\nClaude Code Chat Ingestion Plan")
            print("=" * 50)
            print(f"Mode:                   dry_run")
            print(f"Discovered transcripts:  {discovered_transcripts}")
            print(f"Planned sources:        {planned_sources}")
            print(f"Skipped sessions:       {skipped_sessions}")
            print(f"Failed sessions:        {failed_sessions}")

            if all_skip_reasons:
                print(f"\nSkip/Fail Reasons:")
                for reason, count in all_skip_reasons.items():
                    print(f"  {reason}: {count}")

            print(f"\nMessages:")
            print(f"  Total:      {total_messages}")
            print(f"  User:       {user_messages}")
            print(f"  Assistant:  {assistant_messages}")

            print(f"\nRedactions: {total_redactions}")

            print(f"\nChunking:")
            print(f"  Parents:    {parent_chunks}")
            print(f"  Children:   {child_chunks}")

            print(f"\nOperations (dry-run, no actual changes):")
            print(f"  Database writes: 0")
            print(f"  Embedding requests: 0")
            print(f"  Elapsed: {elapsed_ms}ms")

            print("\nSTEP6D_CHAT_DRY_RUN_OK")

        return 0

    # PHASE 3: Handle --apply mode (requires infrastructure)
    return await apply_ingestion(
        args=args,
        root=root,
        loaded_documents=loaded_documents,
        discovered_transcripts=discovered_transcripts,
        planned_sources=planned_sources,
        skipped_sessions=skipped_sessions,
        failed_sessions=failed_sessions,
        all_skip_reasons=all_skip_reasons,
        total_messages=total_messages,
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        total_redactions=total_redactions,
        parent_chunks=parent_chunks,
        child_chunks=child_chunks,
        sessions=sessions,
        start_time=start_time,
    )


async def apply_ingestion(
    args,
    root: Path,
    loaded_documents: list,
    discovered_transcripts: int,
    planned_sources: int,
    skipped_sessions: int,
    failed_sessions: int,
    all_skip_reasons: dict,
    total_messages: int,
    user_messages: int,
    assistant_messages: int,
    total_redactions: int,
    parent_chunks: int,
    child_chunks: int,
    sessions: list,
    start_time: float,
) -> int:
    """Apply ingestion to database if there are planned sources."""
    # If no planned sources, don't initialize infrastructure
    if planned_sources == 0:
        results = {
            "mode": "apply",
            "discovered_transcripts": discovered_transcripts,
            "project_transcripts": discovered_transcripts,
            "planned_sources": 0,
            "inserted_sources": 0,
            "updated_sources": 0,
            "unchanged_sources": 0,
            "failed_sources": 0,
            "skipped_sessions": skipped_sessions,
            "skip_reasons": all_skip_reasons,
            "parent_chunks": 0,
            "child_chunks": 0,
            "embedded_children": 0,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "failures": [],
        }

        if args.json:
            print(json.dumps(results, indent=2))
            print("\nSTEP6D_CHAT_INGEST_OK", file=sys.stderr)
        else:
            print("\nClaude Code Chat Ingestion")
            print("=" * 50)
            print("No sources to ingest")

            print("\nSTEP6D_CHAT_INGEST_OK")

        return 0

    # Load settings
    try:
        settings = Settings.from_env()
        logger.info(f"Settings loaded: api_base_url={settings.api_base_url}")
    except ConfigurationError as e:
        print(f"ERROR: Failed to load settings: {e}", file=sys.stderr)
        return 1

    # Create database pool
    pool = None
    try:
        pool = create_pool(settings)
        pool.open(wait=True, timeout=settings.db_timeout_seconds)
        logger.info("Database pool created")

        # Create embedding client
        embedding_client = HttpEmbeddingClient(
            api_base_url=settings.api_base_url,
            api_timeout_seconds=settings.api_timeout_seconds,
            embedding_batch_size=settings.embedding_batch_size,
        )
        logger.info("Created HttpEmbeddingClient")

        # Create ingestion service
        service = IngestionService(
            settings=settings,
            embedding_client=embedding_client,
            pool=pool,
        )

        # Perform ingestion
        logger.info("Starting ingestion...")
        result = await service.ingest_sources(
            loaded_documents,
            dry_run=False,
        )

        # Build results
        results = {
            "mode": "apply",
            "discovered_transcripts": discovered_transcripts,
            "project_transcripts": discovered_transcripts,
            "planned_sources": planned_sources,
            "inserted_sources": result.inserted_sources,
            "updated_sources": result.updated_sources,
            "unchanged_sources": result.unchanged_sources,
            "failed_sources": result.failed_sources,
            "skipped_sessions": skipped_sessions,
            "skip_reasons": all_skip_reasons,
            "parent_chunks": result.parent_chunks,
            "child_chunks": result.child_chunks,
            "embedded_children": result.embedded_children,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "failures": [
                {"session_id": f.get("session_id", "unknown"), "reason": f.get("reason", "unknown")}
                for f in result.failures
            ],
        }

        # Output apply results
        if args.json:
            print(json.dumps(results, indent=2))
            # Only print success marker on success
            if result.failed_sources == 0:
                print("\nSTEP6D_CHAT_INGEST_OK", file=sys.stderr)
        else:
            print("\nClaude Code Chat Ingestion")
            print("=" * 50)
            print(f"Discovered transcripts:  {discovered_transcripts}")
            print(f"Planned sources:        {planned_sources}")
            print(f"Inserted:               {result.inserted_sources}")
            print(f"Updated:                {result.updated_sources}")
            print(f"Unchanged:              {result.unchanged_sources}")
            print(f"Failed:                 {result.failed_sources}")

            if all_skip_reasons:
                print(f"\nSkip Reasons:")
                for reason, count in all_skip_reasons.items():
                    print(f"  {reason}: {count}")

            print(f"\nChunking:")
            print(f"  Parents:    {result.parent_chunks}")
            print(f"  Children:   {result.child_chunks}")
            print(f"  Embedded:   {result.embedded_children}")

            if result.failed_sources == 0:
                print("\nSTEP6D_CHAT_INGEST_OK")

        # Return non-zero if any sources failed
        return 1 if result.failed_sources > 0 else 0

    except ConfigurationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("Unexpected error during ingestion")
        print(f"ERROR: Unexpected error during ingestion", file=sys.stderr)
        return 1
    finally:
        if pool:
            pool.close()
            logger.info("Database pool closed")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
