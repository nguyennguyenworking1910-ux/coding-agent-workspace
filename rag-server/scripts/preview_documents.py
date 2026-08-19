#!/usr/bin/env python3
"""Preview local documents without embedding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingestion.chunker import DocumentChunker
from app.ingestion.document_scanner import DocumentScanError, LocalDocumentScanner
from app.ingestion.docx_loader import DocxLoadError, DocxLoader
from app.ingestion.pdf_loader import PdfLoadError, PdfLoader


def main() -> int:
    """Preview documents from the configured directory."""
    parser = argparse.ArgumentParser(
        description="Preview local documents for RAG ingestion",
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
        help="Specific document path to preview (can be repeated)",
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
    chunker = DocumentChunker()

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

    loaded_docs = []

    try:
        # Scan documents
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

                # Chunk document
                plan = chunker.chunk(doc)
                parent_chunks += len(plan.parents)
                child_chunks += len(plan.children)

                for parent in plan.parents:
                    max_parent_chars = max(max_parent_chars, len(parent.content))

                for child in plan.children:
                    max_child_chars = max(max_child_chars, len(child.content))

                loaded_docs.append(
                    {
                        "source_key": doc.source_key,
                        "title": doc.title,
                        "format": scanned.extension[1:].upper(),
                        "file_size_bytes": scanned.file_size_bytes,
                        "content_length": len(doc.content),
                        "parents": len(plan.parents),
                        "children": len(plan.children),
                    }
                )

            except (PdfLoadError, DocxLoadError) as e:
                skip_reasons[e.reason] = skip_reasons.get(e.reason, 0) + 1
                skipped_documents += 1
                continue

    except DocumentScanError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}", file=sys.stderr)
        return 1

    # Output results
    results = {
        "discovered_documents": discovered_documents,
        "loaded_documents": loaded_documents,
        "skipped_documents": skipped_documents,
        "skip_reasons": skip_reasons,
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
        "documents": loaded_docs,
    }

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\nDocument Preview Summary")
        print(f"{'=' * 50}")
        print(f"Discovered:         {discovered_documents}")
        print(f"Loaded:             {loaded_documents}")
        print(f"Skipped:            {skipped_documents}")

        if skip_reasons:
            print(f"\nSkip Reasons:")
            for reason, count in skip_reasons.items():
                print(f"  {reason}: {count}")

        print(f"\nDocument Formats:")
        print(f"  PDF:              {pdf_documents}")
        print(f"  DOCX:             {docx_documents}")

        if pdf_documents > 0:
            print(f"\nPDF Statistics:")
            print(f"  Total Pages:      {total_pdf_pages}")
            print(f"  Pages without text: {pdf_pages_without_text}")

        if docx_documents > 0:
            print(f"\nDOCX Statistics:")
            print(f"  Total Paragraphs: {total_docx_paragraphs}")
            print(f"  Total Tables:     {total_docx_tables}")

        print(f"\nChunking Results:")
        print(f"  Parent Chunks:    {parent_chunks}")
        print(f"  Child Chunks:     {child_chunks}")
        print(f"  Max Parent Chars: {max_parent_chars}")
        print(f"  Max Child Chars:  {max_child_chars}")

        if loaded_docs:
            print(f"\nDocuments:")
            for doc in loaded_docs:
                print(f"  {doc['title']} ({doc['format']})")
                print(f"    Size: {doc['file_size_bytes']} bytes")
                print(f"    Content: {doc['content_length']} chars")
                print(f"    Chunks: {doc['parents']} parents, {doc['children']} children")

    print("\nSTEP6C_DOCUMENT_PREVIEW_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
