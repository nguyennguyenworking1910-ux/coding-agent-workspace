"""Deterministic parent-child chunker for RAG documents."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import NamedTuple

from .models import ChunkDraft, ChunkPlan, LoadedDocument


class ChunkerConfig(NamedTuple):
    """Configuration for chunking behavior."""

    parent_target_chars: int = 1800
    parent_max_chars: int = 2400
    child_target_chars: int = 650
    child_max_chars: int = 900
    child_overlap_chars: int = 100


class TokenEstimator:
    """Estimates token counts deterministically."""

    # Simple heuristic: 1 token ≈ 4 characters on average
    CHARS_PER_TOKEN = 4.0

    @staticmethod
    def estimate(content: str) -> int:
        """Estimate token count using character-based heuristic.

        Args:
            content: Text content

        Returns:
            Estimated token count
        """
        return max(1, int(len(content.strip()) / TokenEstimator.CHARS_PER_TOKEN))


class DocumentChunker:
    """Chunks documents deterministically into parent-child structure."""

    def __init__(self, config: ChunkerConfig | None = None):
        """Initialize chunker with configuration.

        Args:
            config: Chunking configuration (uses defaults if None)
        """
        self.config = config or ChunkerConfig()

    def chunk(self, document: LoadedDocument) -> ChunkPlan:
        """Chunk a document into parent-child structure.

        Args:
            document: Loaded document to chunk

        Returns:
            ChunkPlan with parents and children
        """
        # Determine if document is Markdown
        is_markdown = document.metadata.get("extension") in [
            ".md",
            ".mdx",
        ]

        # Split into parent chunks
        parent_chunks = self._create_parents(
            document.content,
            is_markdown=is_markdown,
        )

        # Create child chunks from parents
        child_chunks = self._create_children(parent_chunks)

        return ChunkPlan(
            document=document,
            parents=parent_chunks,
            children=child_chunks,
        )

    def _create_parents(
        self,
        content: str,
        is_markdown: bool = False,
    ) -> list[ChunkDraft]:
        """Create parent-level chunks.

        For Markdown: Split by headings and paragraphs
        For code: Split by logical sections or hard-split if needed

        Args:
            content: Document content
            is_markdown: Whether to use Markdown-aware splitting

        Returns:
            List of parent ChunkDraft instances with chunk_level='parent'
        """
        if is_markdown:
            return self._split_markdown_parents(content)
        else:
            return self._split_code_parents(content)

    def _split_markdown_parents(self, content: str) -> list[ChunkDraft]:
        """Split Markdown document by headings and paragraphs."""
        parents = []
        current_chunk = ""
        current_heading = None
        parent_index = 0

        # Split by lines to track headings
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # If a single line exceeds max size, hard-split it
            if len(line) > self.config.parent_max_chars:
                # Save current chunk first
                if current_chunk.strip():
                    chunk = self._finalize_parent(
                        current_chunk,
                        parent_index,
                        current_heading,
                    )
                    if chunk:
                        parents.append(chunk)
                        parent_index += 1
                    current_chunk = ""

                # Hard-split the long line
                offset = 0
                while offset < len(line):
                    end = min(
                        offset + self.config.parent_max_chars,
                        len(line),
                    )
                    chunk_text = line[offset:end].strip()
                    if chunk_text:
                        chunk = self._finalize_parent(
                            chunk_text,
                            parent_index,
                            current_heading,
                        )
                        if chunk:
                            parents.append(chunk)
                            parent_index += 1
                    offset = end

                i += 1
                continue

            # Check if this is a heading
            heading_match = re.match(r"^(#{1,6}) +(.+?)$", line)
            if heading_match:
                current_heading = heading_match.group(2).strip()

            # Test if adding this line would exceed max size
            if current_chunk:
                test_chunk = current_chunk + "\n" + line
            else:
                test_chunk = line

            if len(test_chunk) > self.config.parent_max_chars:
                # Would exceed limit - save current chunk and start new
                if current_chunk.strip():
                    chunk = self._finalize_parent(
                        current_chunk,
                        parent_index,
                        current_heading,
                    )
                    if chunk:
                        parents.append(chunk)
                        parent_index += 1

                # Update heading if this line is a heading
                if heading_match:
                    current_heading = heading_match.group(2).strip()

                current_chunk = line
            else:
                # Add line to current chunk
                if current_chunk:
                    current_chunk += "\n" + line
                else:
                    current_chunk = line

            i += 1

        # Add final chunk
        if current_chunk.strip():
            chunk = self._finalize_parent(
                current_chunk,
                parent_index,
                current_heading,
            )
            if chunk:
                parents.append(chunk)

        return parents if parents else self._fallback_split(content)

    def _split_code_parents(self, content: str) -> list[ChunkDraft]:
        """Split code document by logical sections or hard-split."""
        parents = []
        lines = content.split("\n")
        current_chunk_lines = []
        parent_index = 0

        for line in lines:
            # If a single line exceeds max size, hard-split it
            if len(line) > self.config.parent_max_chars:
                # Save current chunk first
                if current_chunk_lines:
                    current_chunk_str = "\n".join(current_chunk_lines)
                    chunk = self._finalize_parent(
                        current_chunk_str,
                        parent_index,
                        None,
                    )
                    if chunk:
                        parents.append(chunk)
                        parent_index += 1
                    current_chunk_lines = []

                # Hard-split the long line
                offset = 0
                while offset < len(line):
                    end = min(
                        offset + self.config.parent_max_chars,
                        len(line),
                    )
                    chunk_text = line[offset:end].strip()
                    if chunk_text:
                        chunk = self._finalize_parent(
                            chunk_text,
                            parent_index,
                            None,
                        )
                        if chunk:
                            parents.append(chunk)
                            parent_index += 1
                    offset = end

                continue

            # Check if adding this line would exceed max size
            test_chunk = (
                "\n".join(current_chunk_lines + [line])
                if current_chunk_lines
                else line
            )

            if len(test_chunk) > self.config.parent_max_chars:
                # Save current chunk if it has content
                if current_chunk_lines:
                    current_chunk_str = "\n".join(current_chunk_lines)
                    chunk = self._finalize_parent(
                        current_chunk_str,
                        parent_index,
                        None,
                    )
                    if chunk:
                        parents.append(chunk)
                        parent_index += 1

                # Start new chunk with current line
                current_chunk_lines = [line]
            else:
                current_chunk_lines.append(line)

        # Add final chunk
        if current_chunk_lines:
            current_chunk_str = "\n".join(current_chunk_lines)
            chunk = self._finalize_parent(
                current_chunk_str,
                parent_index,
                None,
            )
            if chunk:
                parents.append(chunk)

        return parents if parents else self._fallback_split(content)

    def _fallback_split(self, content: str) -> list[ChunkDraft]:
        """Fallback: Split content by fixed character size."""
        parents = []
        parent_index = 0

        # Simple approach: split by target size
        offset = 0
        while offset < len(content):
            end = min(
                offset + self.config.parent_max_chars,
                len(content),
            )

            # Try to find a good split point (newline)
            if end < len(content):
                last_newline = content.rfind("\n", offset, end)
                if last_newline > offset:
                    end = last_newline

            chunk_text = content[offset:end].strip()
            if chunk_text:
                chunk = self._finalize_parent(
                    chunk_text,
                    parent_index,
                    None,
                )
                if chunk:
                    parents.append(chunk)
                    parent_index += 1

            offset = end

        return parents

    def _finalize_parent(
        self,
        text: str,
        parent_index: int,
        current_heading: str | None = None,
    ) -> ChunkDraft | None:
        """Create a finalized parent chunk.

        Args:
            text: Chunk text
            parent_index: Index of this parent
            current_heading: Current Markdown heading context

        Returns:
            ChunkDraft or None if text is empty after strip
        """
        text = text.strip()
        if not text:
            return None

        content_hash = self._compute_hash(text)
        token_count = TokenEstimator.estimate(text)

        metadata = {
            "token_count_method": "estimated",
        }
        if current_heading:
            metadata["heading"] = current_heading

        return ChunkDraft(
            chunk_level="parent",
            chunk_index=parent_index,
            parent_index=None,
            content=text,
            content_hash=content_hash,
            token_count=token_count,
            metadata=metadata,
        )

    def _create_children(
        self,
        parents: list[ChunkDraft],
    ) -> list[ChunkDraft]:
        """Create child chunks from parent chunks with overlap.

        Args:
            parents: List of parent chunks

        Returns:
            List of child ChunkDraft instances
        """
        children = []
        global_child_index = 0

        for parent in parents:
            parent_children = self._split_parent_into_children(
                parent,
                parent_index=parent.chunk_index,
                starting_child_index=global_child_index,
            )

            children.extend(parent_children)
            global_child_index += len(parent_children)

        return children

    def _split_parent_into_children(
        self,
        parent: ChunkDraft,
        parent_index: int,
        starting_child_index: int,
    ) -> list[ChunkDraft]:
        """Split a parent chunk into child chunks with overlap.

        Args:
            parent: Parent chunk to split
            parent_index: Index of the parent
            starting_child_index: Starting index for children

        Returns:
            List of child chunks
        """
        children = []
        content = parent.content
        target = self.config.child_target_chars
        max_size = self.config.child_max_chars
        overlap = self.config.child_overlap_chars

        if len(content) <= target:
            # Single child that is the entire parent
            child = self._finalize_child(
                content,
                chunk_index=starting_child_index,
                parent_index=parent_index,
            )
            if child:
                children.append(child)
            return children

        # Split into multiple children with overlap
        offset = 0
        child_index = starting_child_index

        while offset < len(content):
            # Find end of this child chunk
            end = min(offset + max_size, len(content))

            # Try to find a natural break point (whitespace/newline)
            if end < len(content):
                # Look for whitespace boundary
                last_space = content.rfind(
                    " ",
                    offset + target,
                    end,
                )
                last_newline = content.rfind(
                    "\n",
                    offset + target,
                    end,
                )

                # Use the last natural boundary
                boundary = max(last_space, last_newline)
                if boundary > offset + target:
                    end = boundary

            # Extract child text
            child_text = content[offset:end].strip()
            if child_text:
                child = self._finalize_child(
                    child_text,
                    chunk_index=child_index,
                    parent_index=parent_index,
                )
                if child:
                    children.append(child)
                    child_index += 1

            # Move offset forward, accounting for overlap
            offset = max(offset + target - overlap, offset + 1)

            # Avoid infinite loop on very small content
            if offset >= len(content):
                break

        return children

    def _finalize_child(
        self,
        text: str,
        chunk_index: int,
        parent_index: int,
    ) -> ChunkDraft | None:
        """Create a finalized child chunk.

        Args:
            text: Chunk text
            chunk_index: Global child index
            parent_index: Index of parent

        Returns:
            ChunkDraft or None if text is empty
        """
        text = text.strip()
        if not text:
            return None

        content_hash = self._compute_hash(text)
        token_count = TokenEstimator.estimate(text)

        return ChunkDraft(
            chunk_level="child",
            chunk_index=chunk_index,
            parent_index=parent_index,
            content=text,
            content_hash=content_hash,
            token_count=token_count,
            metadata={
                "token_count_method": "estimated",
            },
        )

    @staticmethod
    def _compute_hash(content: str) -> str:
        """Compute SHA-256 hash of chunk content.

        Args:
            content: Chunk text

        Returns:
            SHA-256 hex digest (64 characters)
        """
        content_bytes = content.encode("utf-8")
        return hashlib.sha256(content_bytes).hexdigest()
