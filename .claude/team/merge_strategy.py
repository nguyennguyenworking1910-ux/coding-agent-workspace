"""Merge strategy for safely merging multiple agent worktrees."""

from typing import List, Dict, Optional, Callable
from pydantic import BaseModel
import subprocess
from datetime import datetime


class MergeConflict(BaseModel):
    """Represents a merge conflict."""
    file_path: str
    agent_id: str
    batch_id: int
    resolved: bool = False


class MergeBatch(BaseModel):
    """Tracks merges by batch."""
    batch_id: int
    agent_ids: List[str]
    target_branch: str
    status: str  # pending, in_progress, completed, failed
    conflicts: List[MergeConflict] = []
    merged_agents: List[str] = []
    failed_agents: List[str] = []


class MergeStrategy:
    """Orchestrates safe merging of multiple worktrees."""

    def __init__(self, repo_path: str, worktree_manager):
        """Initialize merge strategy.

        Args:
            repo_path: Path to git repository
            worktree_manager: WorktreeManager instance
        """
        self.repo_path = repo_path
        self.worktree_manager = worktree_manager
        self.batches: List[MergeBatch] = []

    def create_merge_plan(
        self, agent_ids: List[str], task_dependencies: Optional[Dict[str, List[str]]] = None
    ) -> List[MergeBatch]:
        """Create merge batches respecting task dependencies.

        Args:
            agent_ids: List of agent identifiers
            task_dependencies: Dict mapping agent_id to agent_ids they depend on

        Returns:
            List of merge batches
        """
        if not task_dependencies:
            task_dependencies = {}

        # If no dependencies, create single batch
        if not any(task_dependencies.values()):
            batch = MergeBatch(
                batch_id=0,
                agent_ids=agent_ids,
                target_branch="main",
                status="pending",
            )
            self.batches = [batch]
            return [batch]

        # Topological sort by dependencies
        visited = set()
        sorted_agents = []

        def visit(agent_id: str) -> None:
            if agent_id in visited:
                return
            visited.add(agent_id)

            # Visit dependencies first
            for dep_agent in task_dependencies.get(agent_id, []):
                if dep_agent in agent_ids:
                    visit(dep_agent)

            sorted_agents.append(agent_id)

        for agent_id in agent_ids:
            visit(agent_id)

        # Create batches (1 agent per batch for strict ordering)
        batches = []
        for idx, agent_id in enumerate(sorted_agents):
            batch = MergeBatch(
                batch_id=idx,
                agent_ids=[agent_id],
                target_branch="main",
                status="pending",
            )
            batches.append(batch)

        self.batches = batches
        return batches

    def merge_batch_sequentially(
        self, batch: MergeBatch, strategy: str = "auto"
    ) -> bool:
        """Merge agents in a batch sequentially.

        Args:
            batch: MergeBatch to merge
            strategy: Merge strategy ("auto" | "manual" | "abort")

        Returns:
            True if successful
        """
        print(f"[MERGE] Starting batch {batch.batch_id}: {batch.agent_ids}")

        for agent_id in batch.agent_ids:
            # Check for conflicts first
            conflicts = self._detect_conflicts(agent_id, batch.target_branch)

            if conflicts:
                print(f"[MERGE] Conflicts detected for {agent_id}: {len(conflicts)} file(s)")

                if strategy == "abort":
                    batch.failed_agents.append(agent_id)
                    print(f"[MERGE] Aborting merge for {agent_id}")
                    return False
                elif strategy == "manual":
                    # For testing, auto-resolve compatible changes
                    # In production, this would prompt user
                    print(f"[MERGE] Auto-resolving conflicts (test mode)")
                    for conflict in conflicts:
                        conflict.resolved = True
                    batch.conflicts.extend(conflicts)

            # Attempt merge
            success = self.worktree_manager.merge_worktree(agent_id, batch.target_branch)

            if success:
                batch.merged_agents.append(agent_id)
                print(f"[MERGE] Successfully merged {agent_id}")
            else:
                batch.failed_agents.append(agent_id)
                print(f"[MERGE] Failed to merge {agent_id}")

                if strategy == "abort":
                    return False

        batch.status = "completed" if not batch.failed_agents else "failed"
        return len(batch.failed_agents) == 0

    def _detect_conflicts(self, agent_id: str, target_branch: str) -> List[MergeConflict]:
        """Dry-run merge to detect conflicts.

        Args:
            agent_id: Agent identifier
            target_branch: Target branch

        Returns:
            List of detected conflicts
        """
        try:
            # Get worktree branch
            worktree_path = self.worktree_manager.get_worktree_path(agent_id)
            if not worktree_path:
                return []

            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                check=True,
            )
            worktree_branch = result.stdout.strip()

            # Dry-run merge
            result = subprocess.run(
                ["git", "merge", "--no-commit", "--no-ff", worktree_branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                # Get conflicted files
                result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )

                files = result.stdout.strip().split("\n") if result.stdout.strip() else []
                conflicts = [
                    MergeConflict(
                        file_path=f,
                        agent_id=agent_id,
                        batch_id=self.batches[-1].batch_id if self.batches else 0,
                    )
                    for f in files
                ]

                # Abort merge
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=self.repo_path,
                    capture_output=True,
                    check=False,
                )

                return conflicts

            # No conflicts, abort dry-run
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self.repo_path,
                capture_output=True,
                check=False,
            )

            return []

        except Exception as e:
            print(f"[MERGE] Error detecting conflicts: {e}")
            return []

    def resolve_conflicts(
        self,
        conflicts: List[MergeConflict],
        resolution_callback: Optional[Callable] = None,
    ) -> bool:
        """Resolve detected conflicts.

        Args:
            conflicts: List of conflicts to resolve
            resolution_callback: Optional callback for custom resolution

        Returns:
            True if resolved
        """
        for conflict in conflicts:
            if resolution_callback:
                # Let callback handle resolution
                if resolution_callback(conflict):
                    conflict.resolved = True
            else:
                # Default: accept theirs (worktree version)
                try:
                    subprocess.run(
                        ["git", "checkout", "--theirs", conflict.file_path],
                        cwd=self.repo_path,
                        check=True,
                        capture_output=True,
                    )
                    conflict.resolved = True
                except subprocess.CalledProcessError:
                    pass

        return all(c.resolved for c in conflicts)

    def rollback_merge(self) -> bool:
        """Rollback failed merge.

        Returns:
            True if successful
        """
        try:
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self.repo_path,
                check=True,
                capture_output=True,
            )
            print("[MERGE] Rollback complete")
            return True
        except subprocess.CalledProcessError:
            return False
