"""Tests for Milestone 6: Worktree isolation."""

import sys
import tempfile
import subprocess
from pathlib import Path

# Add .claude to path
claude_path = Path(__file__).parent.parent / ".claude"
if str(claude_path) not in sys.path:
    sys.path.insert(0, str(claude_path))

from team.worktree_manager import WorktreeManager


def create_test_repo(repo_path: str) -> None:
    """Create a minimal git repository for testing.

    Args:
        repo_path: Path to repository
    """
    Path(repo_path).mkdir(parents=True, exist_ok=True)

    # Initialize repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

    # Configure user
    subprocess.run(
        ["git", "config", "user.email", "test@local"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    test_file = Path(repo_path) / "README.md"
    test_file.write_text("# Test Repository\n")

    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def test_worktree_create():
    """Test creating a worktree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)

        # Create worktree
        worktree_path = mgr.create_worktree("researcher", "run_001")

        assert worktree_path.exists(), "Worktree should exist"
        assert (worktree_path / "README.md").exists(), "Worktree should have repo files"
        assert "researcher" in mgr.worktrees, "Worktree should be tracked"


def test_worktree_get_path():
    """Test getting worktree path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)
        mgr.create_worktree("researcher", "run_001")

        path = mgr.get_worktree_path("researcher")
        assert path is not None
        assert path.exists()
        assert "researcher" in str(path)


def test_worktree_status():
    """Test getting worktree status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)
        worktree_path = mgr.create_worktree("researcher", "run_001")

        # Initial status should have no changes
        status = mgr.get_worktree_status("researcher")
        assert status is not None
        assert status["has_changes"] == False

        # Make a change
        test_file = worktree_path / "test.txt"
        test_file.write_text("Test content")

        # Status should now show changes
        status = mgr.get_worktree_status("researcher")
        assert status["has_changes"] == True


def test_worktree_changes():
    """Test getting worktree changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)
        worktree_path = mgr.create_worktree("researcher", "run_001")

        # Modify a file
        readme_path = worktree_path / "README.md"
        readme_path.write_text("# Test Repository\n## Updated\n")

        # Get diff
        changes = mgr.get_worktree_changes("researcher")
        assert changes is not None
        assert "Updated" in changes or "README" in changes


def test_worktree_commit():
    """Test committing worktree changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)
        worktree_path = mgr.create_worktree("researcher", "run_001")

        # Make a change
        test_file = worktree_path / "research.md"
        test_file.write_text("# Research Results\n")

        # Commit
        commit_hash = mgr.commit_worktree_changes(
            "researcher",
            "Added research findings",
            author_name="Researcher Agent",
        )

        assert commit_hash is not None
        assert len(commit_hash) == 40  # SHA-1 hash length


def test_worktree_multiple_agents():
    """Test creating worktrees for multiple agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)

        # Create worktrees for multiple agents
        agents = ["researcher", "implementer", "reviewer"]
        paths = {}

        for agent in agents:
            path = mgr.create_worktree(agent, "run_001")
            paths[agent] = path
            assert path.exists()

        # Verify all tracked
        assert len(mgr.worktrees) == 3

        # Make changes in each
        for agent in agents:
            test_file = paths[agent] / f"{agent}.md"
            test_file.write_text(f"# {agent.title()} Results\n")

        # Verify each has changes
        for agent in agents:
            status = mgr.get_worktree_status(agent)
            assert status["has_changes"] == True


def test_worktree_remove():
    """Test removing a worktree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)
        worktree_path = mgr.create_worktree("researcher", "run_001")

        assert worktree_path.exists()
        assert "researcher" in mgr.worktrees

        # Remove worktree
        success = mgr.remove_worktree("researcher")
        assert success
        assert "researcher" not in mgr.worktrees


def test_worktree_cleanup_all():
    """Test cleaning up all worktrees."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)

        # Create multiple worktrees
        for i in range(3):
            mgr.create_worktree(f"agent_{i}", "run_001")

        assert len(mgr.worktrees) == 3

        # Cleanup all
        count = mgr.cleanup_all_worktrees()
        assert count == 3
        assert len(mgr.worktrees) == 0


def test_worktree_list():
    """Test listing worktrees."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)

        # Create worktrees
        mgr.create_worktree("researcher", "run_001")
        mgr.create_worktree("implementer", "run_001")

        # List
        worktrees = mgr.list_worktrees()
        assert len(worktrees) == 2
        assert any(w["agent_id"] == "researcher" for w in worktrees)
        assert any(w["agent_id"] == "implementer" for w in worktrees)


def test_worktree_isolated_changes():
    """Test that worktrees are isolated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = str(Path(tmpdir) / "repo")
        create_test_repo(repo_path)

        mgr = WorktreeManager(repo_path)

        # Create worktrees
        path_a = mgr.create_worktree("agent_a", "run_001")
        path_b = mgr.create_worktree("agent_b", "run_001")

        # Make different changes
        (path_a / "file_a.txt").write_text("Agent A changes")
        (path_b / "file_b.txt").write_text("Agent B changes")

        # Verify isolation
        assert (path_a / "file_a.txt").exists()
        assert not (path_a / "file_b.txt").exists()
        assert (path_b / "file_b.txt").exists()
        assert not (path_b / "file_a.txt").exists()


if __name__ == "__main__":
    print("Running M6 Worktree tests...")

    test_worktree_create()
    print("[PASS] Create worktree test passed")

    test_worktree_get_path()
    print("[PASS] Get path test passed")

    test_worktree_status()
    print("[PASS] Status test passed")

    test_worktree_changes()
    print("[PASS] Changes test passed")

    test_worktree_commit()
    print("[PASS] Commit test passed")

    test_worktree_multiple_agents()
    print("[PASS] Multiple agents test passed")

    test_worktree_remove()
    print("[PASS] Remove test passed")

    test_worktree_cleanup_all()
    print("[PASS] Cleanup all test passed")

    test_worktree_list()
    print("[PASS] List test passed")

    test_worktree_isolated_changes()
    print("[PASS] Isolated changes test passed")

    print("\n[SUCCESS] ALL M6 WORKTREE TESTS PASSED (10/10)")
