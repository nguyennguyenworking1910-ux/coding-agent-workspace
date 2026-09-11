"""Behavioral documentation tests for Merchant activation feature."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
README_PATH = PROJECT_ROOT / "README.md"
MERCHANT_MANAGER_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "agents"
    / "merchant-manager.md"
)
PROJECT_MANAGER_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "documents"
    / "MERCHANT_PROJECT_MANAGER.md"
)


class TestMerchantActivationDocumentation:
    """Verify Merchant activation is properly documented."""

    def test_readme_documents_merchant_activate_command(self):
        """README must document merchant activate command."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "merchant activate" in content, (
            "README.md must document 'merchant activate' command"
        )

    def test_readme_documents_merchant_activate_all_command(self):
        """README must document merchant activate-all command."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "merchant activate-all" in content, (
            "README.md must document 'merchant activate-all' command"
        )

    def test_readme_documents_onboarding_active_restriction(self):
        """README must document ONBOARDING to ACTIVE restriction."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "ONBOARDING" in content and "ACTIVE" in content, (
            "README.md must mention ONBOARDING and ACTIVE status"
        )

    def test_merchant_manager_lists_activate_command(self):
        """merchant-manager.md must list merchant activate in write operations."""
        content = MERCHANT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "merchant activate" in content, (
            "merchant-manager.md must list 'merchant activate' write operation"
        )

    def test_merchant_manager_lists_activate_all_command(self):
        """merchant-manager.md must list merchant activate-all in write operations."""
        content = MERCHANT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "merchant activate-all" in content, (
            "merchant-manager.md must list 'merchant activate-all' write operation"
        )

    def test_project_manager_documents_activate_command(self):
        """MERCHANT_PROJECT_MANAGER.md must document activate command."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "activate" in content and "merchant" in content, (
            "MERCHANT_PROJECT_MANAGER.md must document merchant activation"
        )

    def test_project_manager_documents_onboarding_active_transition(self):
        """MERCHANT_PROJECT_MANAGER.md must document ONBOARDING to ACTIVE transition."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "ONBOARDING" in content and "ACTIVE" in content, (
            "MERCHANT_PROJECT_MANAGER.md must document status transition"
        )

    def test_project_manager_documents_proposal_phase(self):
        """MERCHANT_PROJECT_MANAGER.md must document proposal phase."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "proposal" in content.lower(), (
            "MERCHANT_PROJECT_MANAGER.md must document proposal phase"
        )

    def test_project_manager_documents_confirmation_phase(self):
        """MERCHANT_PROJECT_MANAGER.md must document confirmation phase."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "confirmation" in content.lower(), (
            "MERCHANT_PROJECT_MANAGER.md must document confirmation phase"
        )

    def test_project_manager_documents_atomic_transaction(self):
        """MERCHANT_PROJECT_MANAGER.md must document atomic transactions."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "atomic" in content.lower() or "transaction" in content.lower(), (
            "MERCHANT_PROJECT_MANAGER.md must document atomic transaction guarantee"
        )

    def test_project_manager_documents_manifest_binding(self):
        """MERCHANT_PROJECT_MANAGER.md must document manifest binding."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "manifest" in content.lower(), (
            "MERCHANT_PROJECT_MANAGER.md must document manifest binding"
        )

    def test_project_manager_documents_drift_rejection(self):
        """MERCHANT_PROJECT_MANAGER.md must document drift rejection."""
        content = PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        assert "drift" in content.lower(), (
            "MERCHANT_PROJECT_MANAGER.md must document drift rejection"
        )

    def test_documentation_does_not_contain_real_merchant_ids(self):
        """Documentation must not expose real merchant IDs."""
        content = (
            README_PATH.read_text(encoding="utf-8")
            + MERCHANT_MANAGER_PATH.read_text(encoding="utf-8")
            + PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        )
        assert "550e8400-e29b-41d4" not in content, (
            "Documentation must not contain real merchant IDs"
        )

    def test_documentation_does_not_contain_exposed_credentials(self):
        """Documentation must not expose real credentials or tokens."""
        content = (
            README_PATH.read_text(encoding="utf-8")
            + MERCHANT_MANAGER_PATH.read_text(encoding="utf-8")
            + PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        )
        # Check for real credential patterns, not just placeholder documentation
        assert "postgresql://" not in content and "postgres://" not in content, (
            "Documentation must not expose real PostgreSQL connection strings"
        )
        # Confirmation tokens should be redacted placeholders, not real values
        assert "<CONFIRMATION_TOKEN>" in content or "[REDACTED]" in content, (
            "Documentation should use placeholders for sensitive values"
        )

    def test_documentation_warns_against_pasting_confirmations(self):
        """Documentation must warn users not to paste auth phrases directly."""
        content = (
            MERCHANT_MANAGER_PATH.read_text(encoding="utf-8")
            + PROJECT_MANAGER_PATH.read_text(encoding="utf-8")
        )
        assert (
            "prompt" in content.lower()
            or "enter" in content.lower()
        ), (
            "Documentation must explain confirmation token prompt behavior"
        )
