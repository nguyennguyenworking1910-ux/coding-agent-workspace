"""Git worktree management for isolated agent modifications."""

import subprocess
import os
from typing import Optional, List, Dict, Any
from pathlib import Path


class WorktreeManager:
    """Manages git worktrees for safe multi-writer execution."""

    def __init__(self, repo_path: str = ".", base_dir: Optional[str] = None):
        """Initialize worktree manager.

        Args:
            repo_path: Path to git repository root
            base_dir: Base directory for worktrees (defaults to .claude/worktrees)
        """
        self.repo_path = Path(repo_path).resolve()
        self.base_dir = Path(base_dir) if base_dir else (self.repo_path / ".claude" / "worktrees")
        self.worktrees: Dict[str, Path] = {}

        # Ensure base directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Verify we're in a git repository
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def create_worktree(self, agent_id: str, run_id: str, branch: Optional[str] = None) -> Path:
        """Create git worktree for an agent.

        Args:
            agent_id: Agent identifier
            run_id: Run identifier
            branch: Branch to check out (defaults to current branch)

        Returns:
            Path to worktree directory

        Raises:
            RuntimeError: If worktree creation fails
        """
        worktree_name = f"{run_id}-{agent_id}"
        worktree_path = self.base_dir / worktree_name

        if worktree_path.exists():
            raise RuntimeError(f"Worktree already exists: {worktree_path}")

        try:
            # Get current branch if not specified
            if branch is None:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                branch = result.stdout.strip()

            # Create worktree with a new branch for this agent
            # This allows multiple worktrees from the same parent branch
            worktree_branch = f"{worktree_name}-branch"
            subprocess.run(
                ["git", "worktree", "add", "-b", worktree_branch, str(worktree_path), branch],
                cwd=self.repo_path,
                check=True,
                capture_output=True,
            )

            self.worktrees[agent_id] = worktree_path
            print(f"[WORKTREE] Created worktree for {agent_id}: {worktree_path}")
            return worktree_path

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e.stderr}")

    def get_worktree_path(self, agent_id: str) -> Optional[Path]:
        """Get path to agent's worktree.

        Args:
            agent_id: Agent identifier

        Returns:
            Path to worktree or None if not found
        """
        return self.worktrees.get(agent_id)

    def get_worktree_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get status of agent's worktree.

        Args:
            agent_id: Agent identifier

        Returns:
            Status dict with changes info or None
        """
        worktree_path = self.get_worktree_path(agent_id)
        if not worktree_path:
            return None

        try:
            # Get git status
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )

            changes = result.stdout.strip().split("\n") if result.stdout.strip() else []

            # Get diff stats
            result = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return {
                "agent_id": agent_id,
                "path": str(worktree_path),
                "has_changes": len(changes) > 0,
                "changes": changes,
                "diff_stat": result.stdout,
            }

        except subprocess.CalledProcessError as e:
            print(f"[WORKTREE] Failed to get status for {agent_id}: {e}")
            return None

    def get_worktree_changes(self, agent_id: str) -> Optional[str]:
        """Get detailed diff for agent's worktree.

        Args:
            agent_id: Agent identifier

        Returns:
            Git diff output or None
        """
        worktree_path = self.get_worktree_path(agent_id)
        if not worktree_path:
            return None

        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout

        except subprocess.CalledProcessError:
            return None

    def commit_worktree_changes(
        self, agent_id: str, message: str, author_name: str = "Agent", author_email: str = "agent@local"
    ) -> Optional[str]:
        """Commit changes in agent's worktree.

        Args:
            agent_id: Agent identifier
            message: Commit message
            author_name: Author name for commit
            author_email: Author email for commit

        Returns:
            Commit hash or None if nothing to commit
        """
        worktree_path = self.get_worktree_path(agent_id)
        if not worktree_path:
            return None

        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=worktree_path,
                check=True,
                capture_output=True,
            )

            # Commit with author info
            result = subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    message,
                    f"--author={author_name} <{author_email}>",
                ],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=False,  # Don't fail if nothing to commit
            )

            if result.returncode == 0:
                # Extract commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                commit_hash = hash_result.stdout.strip()
                print(f"[WORKTREE] Committed changes for {agent_id}: {commit_hash}")
                return commit_hash
            else:
                print(f"[WORKTREE] No changes to commit for {agent_id}")
                return None

        except subprocess.CalledProcessError as e:
            print(f"[WORKTREE] Failed to commit changes for {agent_id}: {e}")
            return None

    def merge_worktree(self, agent_id: str, target_branch: str = "main") -> bool:
        """Merge agent's worktree changes to target branch.

        Args:
            agent_id: Agent identifier
            target_branch: Target branch to merge into (defaults to main)

        Returns:
            True if merge successful, False otherwise
        """
        worktree_path = self.get_worktree_path(agent_id)
        if not worktree_path:
            return False

        try:
            # Switch to target branch in main repo
            subprocess.run(
                ["git", "checkout", target_branch],
                cwd=self.repo_path,
                check=True,
                capture_output=True,
            )

            # Get the branch name from worktree
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            worktree_branch = result.stdout.strip()

            # Merge worktree branch into target
            result = subprocess.run(
                ["git", "merge", worktree_branch, "-m", f"Merge {agent_id} changes"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                print(f"[WORKTREE] Merged {agent_id} into {target_branch}")
                return True
            else:
                print(f"[WORKTREE] Merge conflict for {agent_id}: {result.stderr}")
                return False

        except subprocess.CalledProcessError as e:
            print(f"[WORKTREE] Failed to merge {agent_id}: {e}")
            return False

    def remove_worktree(self, agent_id: str) -> bool:
        """Remove agent's worktree.

        Args:
            agent_id: Agent identifier

        Returns:
            True if successful
        """
        worktree_path = self.get_worktree_path(agent_id)
        if not worktree_path:
            return False

        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                cwd=self.repo_path,
                check=True,
                capture_output=True,
            )

            del self.worktrees[agent_id]
            print(f"[WORKTREE] Removed worktree for {agent_id}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"[WORKTREE] Failed to remove worktree for {agent_id}: {e}")
            return False

    def cleanup_all_worktrees(self) -> int:
        """Remove all managed worktrees.

        Returns:
            Number of worktrees removed
        """
        count = 0
        for agent_id in list(self.worktrees.keys()):
            if self.remove_worktree(agent_id):
                count += 1
        return count

    def list_worktrees(self) -> List[Dict[str, Any]]:
        """List all managed worktrees.

        Returns:
            List of worktree info dicts
        """
        worktrees = []
        for agent_id, path in self.worktrees.items():
            status = self.get_worktree_status(agent_id)
            worktrees.append(
                {
                    "agent_id": agent_id,
                    "path": str(path),
                    "exists": path.exists(),
                    "status": status,
                }
            )
        return worktrees

    def get_conflicted_files(self) -> List[str]:
        """Get list of files with merge conflicts.

        Returns:
            List of conflicted file paths
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().split("\n") if result.stdout.strip() else []

        except subprocess.CalledProcessError:
            return []
