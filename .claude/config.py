"""Configuration management for agent system features."""

import json
from pathlib import Path
from typing import Optional, Dict, Any


class AgentConfig:
    """Manages agent system configuration and feature flags."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration.

        Args:
            config_file: Path to settings.json (auto-detected if None)
        """
        self.config_file = config_file or self._find_settings_file()
        self.config = self._load_config()
        self.env = self.config.get("env", {})

    def _find_settings_file(self) -> str:
        """Find settings.json in .claude directory."""
        current_dir = Path(__file__).parent
        settings_file = current_dir / "settings.json"
        if settings_file.exists():
            return str(settings_file)
        # Fallback to project root
        return str(Path(__file__).parent.parent / ".claude" / "settings.json")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @property
    def experimental_agent_teams_enabled(self) -> bool:
        """Check if experimental agent teams are enabled.

        Returns:
            True if CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is set to "1"
        """
        return self.env.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1"

    @property
    def enable_agent_tracing(self) -> bool:
        """Check if agent tracing should be enabled.

        When experimental teams are enabled, tracing is enabled by default.

        Returns:
            True if tracing should be enabled
        """
        return self.experimental_agent_teams_enabled

    @property
    def enable_structured_logging(self) -> bool:
        """Check if structured logging is enabled.

        When experimental teams are enabled, structured logging is enabled.

        Returns:
            True if structured logging should be enabled
        """
        return self.experimental_agent_teams_enabled

    @property
    def enable_agent_spawning(self) -> bool:
        """Check if agent spawning should be enabled.

        When experimental teams are enabled, actual agent spawning is enabled.

        Returns:
            True if agents should be spawned
        """
        return self.experimental_agent_teams_enabled

    def get_features(self) -> Dict[str, bool]:
        """Get all enabled features.

        Returns:
            Dictionary of feature flags and their status
        """
        return {
            "experimental_agent_teams": self.experimental_agent_teams_enabled,
            "agent_tracing": self.enable_agent_tracing,
            "structured_logging": self.enable_structured_logging,
            "agent_spawning": self.enable_agent_spawning,
        }

    def log_config(self) -> str:
        """Get configuration summary as string.

        Returns:
            Formatted configuration summary
        """
        features = self.get_features()
        summary = "Agent Configuration:\n"
        summary += "=" * 50 + "\n"

        if self.experimental_agent_teams_enabled:
            summary += "[ENABLED] Experimental Agent Teams Mode\n"
            summary += "  - Agent Tracing: ENABLED\n"
            summary += "  - Structured Logging: ENABLED\n"
            summary += "  - Agent Spawning: ENABLED\n"
        else:
            summary += "[DISABLED] Standard Mode\n"
            summary += "  - Agents simulated\n"
            summary += "  - Basic logging only\n"

        summary += "\n" + "=" * 50

        return summary


# Global config instance
_config = None


def get_config() -> AgentConfig:
    """Get or create global configuration instance.

    Returns:
        AgentConfig instance
    """
    global _config
    if _config is None:
        _config = AgentConfig()
    return _config


def is_experimental_mode() -> bool:
    """Check if experimental agent teams are enabled.

    Returns:
        True if experimental mode is active
    """
    return get_config().experimental_agent_teams_enabled
