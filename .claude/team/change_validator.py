"""Validation framework for agent changes before merge."""

from typing import List, Optional
from pydantic import BaseModel
import subprocess
import json
from pathlib import Path


class ValidationError(BaseModel):
    """A validation failure."""
    file_path: str
    error_type: str  # syntax, size, binary, dangerous
    severity: str  # error | warning
    message: str
    agent_id: str


class ValidationResult(BaseModel):
    """Result of validation."""
    agent_id: str
    passed: bool
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []


class ChangeValidator:
    """Validates agent changes before merge."""

    def __init__(self, repo_path: str = "."):
        """Initialize validator.

        Args:
            repo_path: Path to git repository
        """
        self.repo_path = repo_path

    def validate_worktree(self, agent_id: str, worktree_path: str) -> ValidationResult:
        """Run all validations on worktree changes.

        Args:
            agent_id: Agent identifier
            worktree_path: Path to worktree

        Returns:
            ValidationResult
        """
        result = ValidationResult(agent_id=agent_id, passed=True)

        # Get changed files
        try:
            git_result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            changed_files = (
                git_result.stdout.strip().split("\n") if git_result.stdout.strip() else []
            )
        except subprocess.CalledProcessError:
            changed_files = []

        # Validate each changed file
        for file_path in changed_files:
            full_path = Path(worktree_path) / file_path

            if not full_path.exists():
                continue

            # Check file size
            if self._check_file_size(file_path, full_path):
                error = ValidationError(
                    file_path=file_path,
                    error_type="size",
                    severity="error",
                    message=f"File exceeds size limit: {full_path.stat().st_size} bytes",
                    agent_id=agent_id,
                )
                result.errors.append(error)
                result.passed = False

            # Check for binary files
            if self._is_binary(full_path):
                error = ValidationError(
                    file_path=file_path,
                    error_type="binary",
                    severity="error",
                    message="Binary files should not be committed",
                    agent_id=agent_id,
                )
                result.errors.append(error)
                result.passed = False

            # Check syntax for known types
            if self._check_syntax(file_path, full_path):
                error = ValidationError(
                    file_path=file_path,
                    error_type="syntax",
                    severity="error",
                    message="Syntax error detected",
                    agent_id=agent_id,
                )
                result.errors.append(error)
                result.passed = False

        return result

    def _check_file_size(self, file_path: str, full_path: Path) -> bool:
        """Check if file exceeds size limit.

        Args:
            file_path: Relative file path
            full_path: Full file path

        Returns:
            True if file is too large
        """
        MAX_SIZE = 10 * 1024 * 1024  # 10MB
        try:
            return full_path.stat().st_size > MAX_SIZE
        except OSError:
            return False

    def _is_binary(self, file_path: Path) -> bool:
        """Check if file is binary.

        Args:
            file_path: Path to file

        Returns:
            True if binary
        """
        binary_extensions = {".png", ".jpg", ".gif", ".zip", ".tar", ".exe", ".o", ".so"}

        if file_path.suffix.lower() in binary_extensions:
            return True

        # Check file content
        try:
            with open(file_path, "rb") as f:
                content = f.read(512)
                return b"\x00" in content
        except (OSError, IOError):
            return False

    def _check_syntax(self, file_path: str, full_path: Path) -> bool:
        """Check file syntax.

        Args:
            file_path: Relative file path
            full_path: Full file path

        Returns:
            True if syntax error
        """
        suffix = full_path.suffix.lower()

        # Python syntax check
        if suffix == ".py":
            try:
                subprocess.run(
                    ["python", "-m", "py_compile", str(full_path)],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return False
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return True
            except FileNotFoundError:
                # Python not available, skip check
                return False

        # JSON syntax check
        if suffix == ".json":
            try:
                with open(full_path) as f:
                    json.load(f)
                return False
            except (json.JSONDecodeError, OSError):
                return True

        # YAML basic check
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml
                with open(full_path) as f:
                    yaml.safe_load(f)
                return False
            except Exception:
                return True
            except ImportError:
                # PyYAML not available
                return False

        return False
