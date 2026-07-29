"""Utility functions for agent management and naming."""

import re


def convert_to_class_name(agent_name: str) -> str:
    """Convert agent name (snake_case or dash-case) to ClassName.

    Args:
        agent_name: Agent name in snake_case or dash-case (e.g., 'bug_fixer', 'agent-architect')

    Returns:
        Class name in PascalCase (e.g., 'BugFixerAgent', 'AgentArchitectAgent')

    Examples:
        >>> convert_to_class_name('bug_fixer')
        'BugFixerAgent'
        >>> convert_to_class_name('agent_architect')
        'AgentArchitectAgent'
        >>> convert_to_class_name('diagnostician')
        'DiagnosticianAgent'
    """
    # Replace dashes with underscores first
    normalized = agent_name.replace('-', '_')

    # Split on underscores and convert each part to title case
    parts = normalized.split('_')
    pascal_parts = [part.capitalize() for part in parts if part]

    # Join and add Agent suffix
    class_name = ''.join(pascal_parts) + 'Agent'

    return class_name
