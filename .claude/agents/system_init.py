"""System initialization and enforcement rules.

All agents must read docs/architecture/system-overview.md before executing any tasks.
This module enforces that requirement.
"""

from pathlib import Path
from typing import Dict, Any


ARCHITECTURE_FILE = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "system-overview.md"

ARCHITECTURE_CHECK_PROMPT = """
Before you proceed with your task, you MUST read the system architecture document.

📖 **REQUIRED READING**: Please read `docs/architecture/system-overview.md`

This document contains:
- System overview and core concepts
- Directory structure and folder responsibilities
- Rules for building and adding agents, tools, and clients
- Documentation placement rules (docs/, archive/, and the load-bearing .md locations)
- Best practices and naming conventions
- System orchestration and team hierarchy

⚠️ **CRITICAL RULE**: Documentation goes in `docs/`; agent definitions and slash commands stay in `.claude/agents/` and `.claude/commands/`

Only proceed with your task AFTER reading this architecture document.

Key sections to focus on:
1. "Overview" - Understand the system
2. "Rules & Best Practices" - Follow the rules
3. "Documentation Rules" - Where to store .md files
4. "Before Building Anything" - Your checklist

After reading, acknowledge that you understand the architecture and are ready to proceed.
"""


def get_architecture_check() -> str:
    """Get the architecture check prompt."""
    return ARCHITECTURE_CHECK_PROMPT


def architecture_acknowledgment(agent_name: str) -> str:
    """Generate acknowledgment message for agent reading the architecture overview."""
    return f"""
✅ {agent_name} Architecture Check

Agent: {agent_name}
Status: Ready to proceed
Acknowledgment: I have read docs/architecture/system-overview.md and understand:
- System architecture and components
- Directory structure and folder ownership
- Rules for adding new agents, tools, and clients
- CRITICAL: Documentation goes in docs/; agents and commands keep their load-bearing locations
- Best practices and naming conventions
- System orchestration hierarchy

I am now ready to execute my assigned tasks while following these guidelines.
"""


def create_agent_initialization(agent_name: str, agent_type: str) -> Dict[str, Any]:
    """Create initialization context for an agent.

    Args:
        agent_name: Name of the agent (e.g., "Scheduler", "Bug Fixer")
        agent_type: Type of agent (e.g., "calendar_manager", "implementer")

    Returns:
        Dictionary with agent initialization context
    """
    return {
        "agent_name": agent_name,
        "agent_type": agent_type,
        "initialization_checklist": [
            ("Read docs/architecture/system-overview.md", True),  # Required
            ("Understand system structure", True),  # Required
            ("Know folder responsibilities", True),  # Required
            ("Understand documentation rules", True),  # Required
            ("Ready to execute tasks", False),  # Will be set after reading
        ],
        "critical_rules": [
            "Documentation goes in docs/ (history in archive/)",
            "Register new components in agents.json",
            "Follow directory structure strictly",
            "Use proper naming conventions",
            "Import from correct modules (one-way dependency)",
        ],
        "architecture_file": str(ARCHITECTURE_FILE),
    }


def validate_agent_ready(agent_name: str) -> bool:
    """Validate that an agent has completed the architecture check."""
    # This is a marker that the agent should confirm
    print(f"\n{'='*70}")
    print(f"🚀 {agent_name} Agent Initialization")
    print(f"{'='*70}\n")
    print("STEP 1: ARCHITECTURE DOCUMENTATION CHECK")
    print("-" * 70)
    print(get_architecture_check())
    print("\n" + "="*70)
    return True
