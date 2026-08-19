#!/usr/bin/env python
"""Preview RAG ingestion without database writes or embedding calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Add rag-server directory to path for imports
rag_server_dir = Path(__file__).parent.parent
sys.path.insert(0, str(rag_server_dir))

from app.ingestion.loaders import DocumentLoader, LoaderError
from app.ingestion.chunker import DocumentChunker
from app.ingestion.scanner import RepositoryScanner
from app.ingestion.filters import FileFilter


def preview_ingestion(
    root: str,
    path: str | None = None,
) -> None:
    """Preview ingestion for a file or directory.

    Args:
        root: Repository root directory
        path: Relative path to file or directory (None = scan entire repo)
    """
    repository_root = Path(root).resolve()

    if not repository_root.is_dir():
        print(f"Error: Repository root not found: {root}", file=sys.stderr)
        sys.exit(1)

    # Discover files using RepositoryScanner
    try:
        scanner = RepositoryScanner(repository_root)
        all_files, skip_reasons = scanner.scan()
    except Exception as e:
        print(f"Error scanning repository: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter to requested path if specified
    files_to_process = all_files
    if path:
        target_path = (repository_root / path).resolve()

        if target_path.is_file():
            # Single file - check if it's in scanner results
            if target_path in all_files:
                files_to_process = [target_path]
            else:
                # File was filtered by scanner
                files_to_process = []
        elif target_path.is_dir():
            # Directory - filter to only files under target directory
            files_to_process = [
                f for f in all_files
                if f.is_relative_to(target_path)
            ]
        else:
            print(f"Error: Path not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Process files
    allowed = len(files_to_process)
    loaded = 0
    loaded_skip_reasons: dict[str, int] = defaultdict(int)
    parent_chunks = 0
    child_chunks = 0
    max_parent_chars = 0
    max_child_chars = 0
    source_types: dict[str, int] = defaultdict(int)

    chunker = DocumentChunker()

    for file_path in files_to_process:
        try:
            # Load document
            document = DocumentLoader.load(
                file_path,
                repository_root,
            )
            loaded += 1

            # Track source type
            source_types[document.source_type] += 1

            # Chunk document
            plan = chunker.chunk(document)

            # Track chunks
            parent_chunks += len(plan.parents)
            child_chunks += len(plan.children)

            # Track max sizes
            for parent in plan.parents:
                max_parent_chars = max(
                    max_parent_chars,
                    len(parent.content),
                )
            for child in plan.children:
                max_child_chars = max(
                    max_child_chars,
                    len(child.content),
                )

        except LoaderError as e:
            loaded_skip_reasons["LoaderError"] = (
                loaded_skip_reasons.get("LoaderError", 0) + 1
            )
        except Exception as e:
            loaded_skip_reasons[type(e).__name__] = (
                loaded_skip_reasons.get(type(e).__name__, 0) + 1
            )

    # Prepare output
    skipped = allowed - loaded
    summary = {
        "discovered": len(all_files) + sum(skip_reasons.values()),
        "allowed": allowed,
        "loaded": loaded,
        "skipped": skipped,
        "parent_chunks": parent_chunks,
        "child_chunks": child_chunks,
        "max_parent_chars": max_parent_chars,
        "max_child_chars": max_child_chars,
        "source_types": dict(source_types),
        "skip_reasons": {**skip_reasons, **loaded_skip_reasons},
    }

    # Print JSON summary
    print(json.dumps(summary, indent=2))

    # Print success indicator
    print("STEP6_PREVIEW_OK")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Preview RAG ingestion without database writes"
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="Repository root directory (default: current directory)",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="File or directory to process (default: entire repository)",
    )

    args = parser.parse_args()

    try:
        preview_ingestion(args.root, args.path)
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
