"""Agent Architect - Designs and generates new agent implementations."""

import re
from typing import List, Dict
from datetime import datetime
from ..base_agent import BaseAgent
from ..agent_utils import convert_to_class_name


class AgentArchitectAgent(BaseAgent):
    """Designs and generates new agent implementations."""

    def __init__(self):
        super().__init__("agent_architect", "architect", "write", ["thought", "read", "write", "glob"])

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Design and generate new agent based on requirements.

        Args:
            task: Agent creation request
            run_id: Unique run ID

        Returns:
            Agent design and generation results
        """
        self._print_header(task, run_id)

        print(f"[i] [AGENT_ARCHITECT] Agent initialized")

        # Step 1: Analyze requirements
        requirements = self._analyze_requirements(task)
        print(f"[i] [AGENT_ARCHITECT] Analyzed requirements")
        print(f"    - Name: {requirements['agent_name']}")
        print(f"    - Type: {requirements['agent_type']}")
        print(f"    - Department: {requirements['department']}")

        # Step 2: Design agent
        design = self._design_agent(task, requirements)
        print(f"[i] [AGENT_ARCHITECT] Agent design complete")
        print(f"    - Class: {design['class_name']}")
        print(f"    - Path: {design['implementation_path']}")

        # Step 3: Generate agent code
        agent_code = self._generate_agent_code(design)
        print(f"[i] [AGENT_ARCHITECT] Agent code generated ({len(agent_code)} bytes)")

        # Step 4: Generate supporting files
        supporting_files = self._generate_supporting_files(design)
        print(f"[i] [AGENT_ARCHITECT] Supporting files generated")

        self._print_footer()

        return self._agent_result(
            success=True,
            task=task,
            response=f"Agent design and code generation complete",
            thinking=f"Designed new '{design['name']}' agent with {len(design['tools'])} tools",
            design=design,
            agent_code=agent_code,
            supporting_files=supporting_files,
            implementation_path=design.get("implementation_path"),
            registration_updates=self._generate_registration_updates(design),
            tools_used=self.tools,
            status="design_complete",
        )

    def _analyze_requirements(self, task: str) -> Dict:
        """Analyze agent requirements from task description."""
        task_lower = task.lower()

        return {
            "agent_name": self._extract_agent_name(task),
            "agent_type": self._extract_agent_type(task),
            "department": self._extract_department(task),
            "purpose": self._extract_purpose(task),
            "tools_needed": self._extract_tools_needed(task),
            "responsibilities": self._extract_responsibilities(task),
        }

    def _design_agent(self, task: str, requirements: Dict) -> Dict:
        """Design new agent structure."""
        name = requirements["agent_name"]

        return {
            "name": name,
            "class_name": convert_to_class_name(name),
            "type": requirements["agent_type"],
            "department": requirements["department"],
            "purpose": requirements["purpose"],
            "mode": self._determine_mode(requirements),
            "tools": requirements["tools_needed"],
            "implementation_path": self._get_implementation_path(requirements),
            "created_date": datetime.now().isoformat(),
        }

    def _generate_agent_code(self, design: Dict) -> str:
        """Generate complete agent class code."""
        tools_list = ', '.join([f'"{tool}"' for tool in design["tools"]])

        code = f'''"""'{design["class_name"]}' Agent - {design["purpose"]}."""

from tools import get_tool


class {design["class_name"]}:
    """{design["type"].capitalize()} agent: {design["purpose"]}."""

    def __init__(self):
        self.name = "{design["name"]}"
        self.type = "{design["type"]}"
        self.mode = "{design["mode"]}"
        self.tools = [{tools_list}]
        self._init_tools()

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def execute(self, task: str, run_id: str = "default") -> dict:
        """Execute {design["name"]} task.

        Args:
            task: Task description
            run_id: Unique run ID

        Returns:
            Execution results
        """
        print(f"\\n{{'='*70}}")
        print(f"AGENT: {design['name'].upper()}")
        print(f"RUN ID: {{run_id}}")
        print(f"TASK: {{task}}")
        print(f"{{'='*70}}\\n")

        print(f"[i] [{design['name'].upper()}] Agent initialized")

        # TODO: Implement agent logic for: {design["purpose"]}
        print(f"[i] [{design['name'].upper()}] Processing task...")

        print(f"\\n{{'='*70}}")
        print(f"STATUS: COMPLETED")
        print(f"{{'='*70}}\\n")

        return {{
            "success": True,
            "agent": "{design["name"]}",
            "task": task,
            "response": "Task completed successfully",
            "thinking": "Executed {design["name"]} task",
            "tools_used": self.tools,
            "status": "completed"
        }}
'''
        return code

    def _generate_supporting_files(self, design: Dict) -> Dict:
        """Generate supporting files (tests, docs, config)."""
        return {
            "test_file": self._generate_test_file(design),
            "docstring": self._generate_documentation(design),
        }

    def _generate_registration_updates(self, design: Dict) -> Dict:
        """Generate needed updates to registration files."""
        department = design["department"]

        return {
            "department_init": {
                "file": f".claude/agents/{department}/__init__.py",
                "imports": f"from .{design['name']} import {design['class_name']}",
                "registry_entry": f'    "{design["name"]}": {design["class_name"]},',
                "exports": design["class_name"],
            },
            "agents_init": {
                "file": ".claude/agents/__init__.py",
                "imports": f"from .{department}.{design['name']} import {design['class_name']}",
                "registry_entry": f'    "{design["name"]}": {design["class_name"]},',
            }
        }

    def _generate_test_file(self, design: Dict) -> str:
        """Generate test file for new agent."""
        return f'''"""Tests for {design["class_name"]}."""

import pytest
from agents.{design["department"]}.{design["name"]} import {design["class_name"]}


class Test{design["class_name"]}:
    """Test {design["class_name"]}."""

    def test_initialization(self):
        agent = {design["class_name"]}()
        assert agent.name == "{design["name"]}"
        assert agent.type == "{design["type"]}"

    def test_execute(self):
        agent = {design["class_name"]}()
        result = agent.execute("Test task")
        assert result["success"]
        assert result["agent"] == "{design["name"]}"
'''

    def _generate_documentation(self, design: Dict) -> str:
        """Generate documentation for new agent."""
        return f"""# {design["class_name"]}

## Purpose
{design["purpose"]}

## Type
{design["type"].capitalize()}

## Mode
{design["mode"]}

## Tools
{", ".join(design["tools"])}

## Created
{design["created_date"]}

## Usage
```python
from agents import {design["class_name"]}

agent = {design["class_name"]}()
result = agent.execute("Your task here")
```
"""

    # ===== Helper Methods =====

    def _extract_agent_name(self, task: str) -> str:
        """Extract agent name from task."""
        import re

        task_lower = task.lower()

        # Look for pattern: "agent [name]" or "[name] agent"
        patterns = [
            r"agent\s+(?:called\s+)?['\"]?(\w+)['\"]?",
            r"['\"]?(\w+)['\"]?\s+agent",
            r"called\s+['\"]?(\w+)['\"]?",
        ]

        for pattern in patterns:
            match = re.search(pattern, task_lower)
            if match:
                name = match.group(1)
                # Convert to snake_case
                name = re.sub(r'([A-Z]+)', r'_\1', name).lower().strip('_')
                return name

        # Fallback: extract first noun
        return "custom_agent"

    def _extract_agent_type(self, task: str) -> str:
        """Determine agent type from task."""
        task_lower = task.lower()

        if any(word in task_lower for word in ["analyze", "scan", "diagnose", "detect", "read", "review"]):
            return "analyzer"
        elif any(word in task_lower for word in ["implement", "fix", "build", "create", "write", "generate"]):
            return "implementer"
        elif any(word in task_lower for word in ["validate", "check", "verify", "test"]):
            return "validator"

        return "generic"

    def _extract_department(self, task: str) -> str:
        """Determine department from task."""
        task_lower = task.lower()

        if any(word in task_lower for word in ["sales", "business", "data", "operations", "revenue", "customer"]):
            return "business"

        return "technical"

    def _extract_purpose(self, task: str) -> str:
        """Extract agent purpose from task."""
        import re

        task_lower = task.lower()

        # Try to extract purpose after specific patterns
        patterns = [
            r"(?:designed to|purpose is|responsibility to|that|with responsibility to)\s+(.+?)(?:\.|$)",
            r"to\s+(.+?)(?:\.|$)",
            r"for\s+(.+?)(?:\.|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, task_lower)
            if match:
                return match.group(1).strip()[:100]

        return task[:100]

    def _extract_tools_needed(self, task: str) -> List[str]:
        """Extract required tools from task."""
        tools = ["thought"]
        task_lower = task.lower()

        if any(word in task_lower for word in ["read", "analyze", "scan", "review", "examine"]):
            tools.extend(["read", "grep", "glob"])
        if any(word in task_lower for word in ["write", "create", "modify", "generate", "fix", "implement"]):
            tools.extend(["write", "edit"])
        if any(word in task_lower for word in ["search", "find", "lookup"]):
            tools.extend(["grep", "glob"])
        if any(word in task_lower for word in ["execute", "run", "command", "bash"]):
            tools.append("bash")

        return list(set(tools))

    def _extract_responsibilities(self, task: str) -> List[str]:
        """Extract agent responsibilities."""
        responsibilities = []

        # Simple extraction - could be more sophisticated
        import re

        # Look for bullet points or comma-separated items
        lines = task.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith(('-', '*', '•')) or ',' in line:
                responsibilities.append(line.lstrip('-*•').strip())

        return responsibilities if responsibilities else ["Process tasks"]

    def _determine_mode(self, requirements: Dict) -> str:
        """Determine read/write mode based on agent type."""
        if requirements["agent_type"] == "implementer":
            return "write"
        return "read-only"

    def _get_implementation_path(self, requirements: Dict) -> str:
        """Get file path for agent implementation."""
        dept = requirements["department"]
        agent_name = requirements["agent_name"]
        return f".claude/agents/{dept}/{agent_name}.py"
