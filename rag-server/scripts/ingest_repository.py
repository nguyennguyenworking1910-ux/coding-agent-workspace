"""CLI script for ingesting repository documents into RAG."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.database import create_pool
from app.ingestion.embedding_client import HttpEmbeddingClient
from app.ingestion.filters import FileFilter
from app.ingestion.loaders import DocumentLoader, LoaderError
from app.ingestion.scanner import RepositoryScanner
from app.ingestion.service import IngestionService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Main entry point for ingestion CLI."""
    parser = argparse.ArgumentParser(
        description="Ingest repository documents into RAG",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )
    parser.add_argument(
        "--path",
        type=str,
        action="append",
        dest="paths",
        help="Path(s) to ingest (relative to root, required, can be multiple)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform no database writes or embedding calls",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.paths:
        print("ERROR: At least one --path argument is required", file=sys.stderr)
        return 1

    root = args.root.resolve()
    if not root.exists():
        print(f"ERROR: Root directory does not exist: {root}", file=sys.stderr)
        return 1

    logger.info(f"Repository root: {root}")
    logger.info(f"Paths to ingest: {args.paths}")
    if args.dry_run:
        logger.info("DRY RUN MODE - No writes will be performed")

    # Load settings
    try:
        settings = Settings.from_env()
        logger.info(f"Settings loaded: api_base_url={settings.api_base_url}")
    except Exception as e:
        print(f"ERROR: Failed to load settings: {e}", file=sys.stderr)
        return 1

    # Create database pool
    try:
        pool = create_pool(settings)
        pool.open(wait=True, timeout=settings.db_timeout_seconds)
        logger.info("Database pool created")
    except Exception as e:
        print(f"ERROR: Failed to create database pool: {e}", file=sys.stderr)
        return 1

    try:
        # Discover files using RepositoryScanner (respects .gitignore)
        logger.info("Discovering files with git ls-files...")
        try:
            scanner = RepositoryScanner(root)
            all_files, skip_reasons = scanner.scan()
            logger.info(
                f"Scanner found {len(all_files)} allowed files. "
                f"Skip reasons: {skip_reasons}"
            )
        except RuntimeError as e:
            print(f"ERROR: Failed to scan repository: {e}", file=sys.stderr)
            return 1

        # Filter to requested paths if specified
        documents_to_load = []
        requested_paths = set()

        if args.paths:
            # User specified paths - filter all_files to only those
            for path_str in args.paths:
                # Normalize to POSIX path
                requested_path = Path(path_str)
                target_path = (root / requested_path).resolve()

                # Track requested path (for checking if none matched)
                requested_paths.add(path_str)

                logger.info(f"Processing requested path: {path_str}")

                if not target_path.exists():
                    logger.warning(f"Requested path not found: {target_path}")
                    continue

                if target_path.is_file():
                    # Single file - verify it's in scanner results
                    if target_path in all_files:
                        documents_to_load.append(target_path)
                        logger.info(f"Added file: {target_path}")
                    else:
                        # File exists but was filtered by scanner
                        filter_result = FileFilter.filter_path(target_path, root)
                        logger.warning(
                            f"File filtered: {target_path} "
                            f"({filter_result.reason})"
                        )
                elif target_path.is_dir():
                    # Directory - filter scanner results to that directory
                    matching = [
                        f for f in all_files
                        if f.is_relative_to(target_path) or f == target_path
                    ]
                    documents_to_load.extend(matching)
                    logger.info(
                        f"Found {len(matching)} files in {target_path}"
                    )
        else:
            # No paths specified - use all discovered files
            documents_to_load = all_files

        # Deduplicate and sort for deterministic order
        documents_to_load = sorted(set(documents_to_load))
        logger.info(f"Found {len(documents_to_load)} files to load")

        # Load documents
        loaded_documents = []
        for file_path in documents_to_load:
            try:
                doc = DocumentLoader.load(file_path, root)
                loaded_documents.append(doc)
                logger.info(f"Loaded: {doc.source_key}")
            except LoaderError as e:
                logger.warning(f"Failed to load {file_path}: {e}")

        logger.info(f"Successfully loaded {len(loaded_documents)} documents")

        # Create ingestion service
        embedding_client = HttpEmbeddingClient(
            api_base_url=settings.api_base_url,
            api_timeout_seconds=settings.api_timeout_seconds,
            embedding_batch_size=settings.embedding_batch_size,
        )

        service = IngestionService(
            settings=settings,
            embedding_client=embedding_client,
            pool=pool,
        )

        # Perform ingestion
        logger.info("Starting ingestion...")
        result = await service.ingest_sources(
            loaded_documents,
            dry_run=args.dry_run,
        )

        # Output results
        if args.json:
            output = {
                "discovered_sources": result.discovered_sources,
                "inserted_sources": result.inserted_sources,
                "updated_sources": result.updated_sources,
                "unchanged_sources": result.unchanged_sources,
                "failed_sources": result.failed_sources,
                "parent_chunks": result.parent_chunks,
                "child_chunks": result.child_chunks,
                "embedded_children": result.embedded_children,
                "elapsed_ms": result.elapsed_ms,
                "failures": result.failures,
            }
            print(json.dumps(output, indent=2))
        else:
            print("\n" + "=" * 60)
            print("INGESTION RESULTS")
            print("=" * 60)
            print(f"Discovered sources:  {result.discovered_sources}")
            print(f"Inserted sources:    {result.inserted_sources}")
            print(f"Updated sources:     {result.updated_sources}")
            print(f"Unchanged sources:   {result.unchanged_sources}")
            print(f"Failed sources:      {result.failed_sources}")
            print(f"Parent chunks:       {result.parent_chunks}")
            print(f"Child chunks:        {result.child_chunks}")
            print(f"Embedded children:   {result.embedded_children}")
            print(f"Elapsed time:        {result.elapsed_ms:.2f}ms")

            if result.failures:
                print("\nFailures:")
                for failure in result.failures:
                    print(
                        f"  - {failure['source_key']}: {failure['error_type']}"
                    )

            print("=" * 60)

        # Determine exit code
        if result.failed_sources > 0:
            if args.dry_run:
                print("\nSTEP6_INGEST_DRY_RUN_OK")
            else:
                print(
                    "\nERROR: Some sources failed to ingest",
                    file=sys.stderr,
                )
                return 1
        else:
            if args.dry_run:
                print("\nSTEP6_INGEST_DRY_RUN_OK")
            else:
                print("\nSTEP6_DATABASE_INGEST_OK")

        return 0

    finally:
        pool.close()
        logger.info("Database pool closed")


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
