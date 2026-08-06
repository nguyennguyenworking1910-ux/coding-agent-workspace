"""Validation framework for changes."""

from typing import List
from pydantic import BaseModel


class ValidationError(BaseModel):
    """A validation failure."""
    file_path: str
    error_type: str  # syntax, size, binary, dangerous
    severity: str  # error | warning
    message: str


class ValidationResult(BaseModel):
    """Result of validation."""
    passed: bool
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []


class Validator:
    """Validates changes and code."""

    def __init__(self, repo_path: str = "."):
        """Initialize validator."""
        self.repo_path = repo_path

    def validate(self, content: str) -> ValidationResult:
        """
        Validate content.

        Args:
            content: Content to validate

        Returns:
            ValidationResult with any errors/warnings
        """
        return ValidationResult(passed=True)
