#!/usr/bin/env python3
"""Ingest local documents with embeddings."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings, ConfigurationError
from app.database import create_pool
from app.ingestion.document_scanner import DocumentScanError, LocalDocumentScanner
from app.ingestion.docx_loader import DocxLoadError, DocxLoader
from app.ingestion.embedding_client import EmbeddingClient, HttpEmbeddingClient
from app.ingestion.pdf_loader import PdfLoadError, PdfLoader
from app.ingestion.service import IngestionService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DryRunEmbeddingClient:
    """Embedding client that rejects all calls in dry-run mode."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Raise AssertionError if called during dry-run."""
        raise AssertionError(
            "embed_texts() should never be called during dry-run mode"
        )


async def main() -> int:
    """Ingest documents into RAG database."""
    parser = argparse.ArgumentParser(
        description="Ingest local documents for RAG",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="Repository root directory (default: current dir)",
    )
    parser.add_argument(
        "--path",
        type=str,
        action="append",
        dest="paths",
        help="Specific document path to ingest (can be repeated)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making database changes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Resolve root
    root = Path(args.root).resolve()
    documents_dir = root / "rag-data" / "documents"

    # Initialize scanner and loaders
    try:
        scanner = LocalDocumentScanner(documents_dir)
    except DocumentScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    pdf_loader = PdfLoader()
    docx_loader = DocxLoader()

    # Load settings early
    try:
        settings = Settings.from_env()
        logger.info(f"Settings loaded: api_base_url={settings.api_base_url}")
    except ConfigurationError as e:
        print(f"ERROR: Failed to load settings: {e}", file=sys.stderr)
        return 1

    # Collect results
    discovered_documents = 0
    loaded_documents = 0
    skipped_documents = 0
    skip_reasons: dict[str, int] = {}

    pdf_documents = 0
    docx_documents = 0

    total_pdf_pages = 0
    pdf_pages_without_text = 0
    total_docx_paragraphs = 0
    total_docx_tables = 0

    parent_chunks = 0
    child_chunks = 0
    max_parent_chars = 0
    max_child_chars = 0

    loaded_documents_list = []

    try:
        # Scan and load documents first (before creating pool/client)
        if args.paths:
            scan_iter = (scanner.scan_path(p) for p in args.paths)
        else:
            scan_iter = scanner.scan()

        for scanned in scan_iter:
            discovered_documents += 1

            # Load document
            try:
                if scanned.extension == ".pdf":
                    doc = pdf_loader.load(
                        scanned.file_path,
                        scanned.relative_posix_path,
                        scanned.file_sha256,
                    )
                    pdf_documents += 1
                    if "page_count" in doc.metadata:
                        total_pdf_pages += doc.metadata["page_count"]
                    if "pages_without_text" in doc.metadata:
                        pdf_pages_without_text += len(
                            doc.metadata["pages_without_text"]
                        )
                elif scanned.extension == ".docx":
                    doc = docx_loader.load(
                        scanned.file_path,
                        scanned.relative_posix_path,
                        scanned.file_sha256,
                    )
                    docx_documents += 1
                    if "paragraph_count" in doc.metadata:
                        total_docx_paragraphs += doc.metadata["paragraph_count"]
                    if "table_count" in doc.metadata:
                        total_docx_tables += doc.metadata["table_count"]
                else:
                    skip_reasons["unsupported_format"] = (
                        skip_reasons.get("unsupported_format", 0) + 1
                    )
                    skipped_documents += 1
                    continue

                loaded_documents += 1
                loaded_documents_list.append(doc)

            except (PdfLoadError, DocxLoadError) as e:
                skip_reasons[e.reason] = skip_reasons.get(e.reason, 0) + 1
                skipped_documents += 1
                continue

    except DocumentScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("Unexpected error during document loading")
        print(f"ERROR: Unexpected error: {e}", file=sys.stderr)
        return 1

    # If all requested documents failed, return early
    if args.paths and loaded_documents == 0:
        results = {
            "discovered_documents": discovered_documents,
            "loaded_documents": 0,
            "skipped_documents": skipped_documents,
            "skip_reasons": skip_reasons,
            "ingested_documents": 0,
            "failed_documents": 0,
            "pdf_documents": pdf_documents,
            "docx_documents": docx_documents,
            "total_pdf_pages": total_pdf_pages,
            "pdf_pages_without_text": pdf_pages_without_text,
            "total_docx_paragraphs": total_docx_paragraphs,
            "total_docx_tables": total_docx_tables,
            "parent_chunks": 0,
            "child_chunks": 0,
            "max_parent_chars": 0,
            "max_child_chars": 0,
        }

        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"\nDocument Ingestion Summary")
            print(f"{'=' * 50}")
            print(f"Discovered:         {discovered_documents}")
            print(f"Loaded:             {loaded_documents}")
            print(f"Skipped:            {skipped_documents}")

            if skip_reasons:
                print(f"\nSkip Reasons:")
                for reason, count in skip_reasons.items():
                    print(f"  {reason}: {count}")

        print(
            f"\nERROR: All requested document(s) failed to load",
            file=sys.stderr,
        )
        return 1

    # Only create pool and client if we have documents to ingest
    pool = None

    try:
        if loaded_documents > 0:
            # Create embedding client
            if args.dry_run:
                embedding_client = DryRunEmbeddingClient()
                logger.info("Using DryRunEmbeddingClient (no actual embeddings)")
            else:
                embedding_client = HttpEmbeddingClient(
                    api_base_url=settings.api_base_url,
                    api_timeout_seconds=settings.api_timeout_seconds,
                    embedding_batch_size=settings.embedding_batch_size,
                )
                logger.info("Created HttpEmbeddingClient")

            # Create database pool
            pool = create_pool(settings)
            pool.open(wait=True, timeout=settings.db_timeout_seconds)
            logger.info("Database pool created")

            # Create ingestion service
            service = IngestionService(
                settings=settings,
                embedding_client=embedding_client,
                pool=pool,
            )

            # Perform ingestion
            logger.info("Starting ingestion...")
            result = await service.ingest_sources(
                loaded_documents_list,
                dry_run=args.dry_run,
            )

            # Calculate chunk counts from results
            parent_chunks = result.parent_chunks
            child_chunks = result.child_chunks

            # Build results
            results = {
                "discovered_documents": discovered_documents,
                "loaded_documents": loaded_documents,
                "skipped_documents": skipped_documents,
                "skip_reasons": skip_reasons,
                "ingested_documents": result.inserted_sources + result.updated_sources,
                "failed_documents": result.failed_sources,
                "pdf_documents": pdf_documents,
                "docx_documents": docx_documents,
                "total_pdf_pages": total_pdf_pages,
                "pdf_pages_without_text": pdf_pages_without_text,
                "total_docx_paragraphs": total_docx_paragraphs,
                "total_docx_tables": total_docx_tables,
                "parent_chunks": parent_chunks,
                "child_chunks": child_chunks,
                "max_parent_chars": max_parent_chars,
                "max_child_chars": max_child_chars,
            }

            # Output results
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                print(f"\nDocument Ingestion Summary")
                print(f"{'=' * 50}")
                print(f"Discovered:         {discovered_documents}")
                print(f"Loaded:             {loaded_documents}")
                print(f"Skipped:            {skipped_documents}")
                print(f"Inserted:           {result.inserted_sources}")
                print(f"Updated:            {result.updated_sources}")
                print(f"Unchanged:          {result.unchanged_sources}")
                print(f"Failed:             {result.failed_sources}")

                if skip_reasons:
                    print(f"\nSkip Reasons:")
                    for reason, count in skip_reasons.items():
                        print(f"  {reason}: {count}")

            # Return error if any explicitly requested document failed
            if args.paths and result.failed_sources > 0:
                print(
                    f"\nERROR: {result.failed_sources} requested document(s) failed",
                    file=sys.stderr,
                )
                return 1

    except ConfigurationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("Error during ingestion")
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        if pool:
            pool.close()

    if args.dry_run:
        print("\nSTEP6C_DOCUMENT_DRY_RUN_OK")
    else:
        print("\nSTEP6C_DOCUMENT_INGEST_OK")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
