"""Team Leader Agent - Orchestrates the agent team."""

import uuid
from datetime import datetime
from tools import get_tool
from config import get_config


class TeamLeaderAgent:
    """Orchestrator agent that coordinates other specialist agents."""

    # Task type patterns for intelligent routing
    TASK_PATTERNS = {
        "security": [
            "security", "vulnerabilities", "exploit", "breach", "vulnerability",
            "penetration", "threat", "attack", "injection", "xss", "csrf",
            "authentication", "authorization", "credentials", "secrets"
        ],
        "bug_analysis": [
            "bug", "error", "issue", "problem", "crash", "broken", "fail",
            "exception", "trace", "debug", "diagnose", "analyze code"
        ],
        "performance": [
            "performance", "slow", "memory", "leak", "optimization",
            "optimize", "efficient", "latency", "throughput", "benchmark"
        ],
        "quality": [
            "quality", "review", "validate", "check", "test", "refactor",
            "structure", "design", "architecture", "pattern", "best practice"
        ],
        "data_operations": [
            "query", "bigquery", "sales", "data", "aggregate", "export",
            "dataset", "table", "group", "analyze sales"
        ]
    }

    def __init__(self):
        self.name = "team_leader"
        self.type = "coordinator"
        self.mode = "read-only"
        self.tools = ["thought"]

        # Experimental features
        self.config = get_config()
        self.experimental_mode = self.config.experimental_agent_teams_enabled
        self.trace_id = str(uuid.uuid4())[:8]  # Unique trace for this execution
        self.execution_log = []

        self._init_tools()

        # Log initialization if experimental mode
        if self.experimental_mode:
            self._log_event("INIT", "Team Leader initialized in experimental mode")

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def _log_event(self, event_type: str, message: str, data: dict = None):
        """Log event for tracing (experimental mode).

        Args:
            event_type: Type of event (INIT, CLASSIFY, SPAWN, etc)
            message: Event description
            data: Optional event data
        """
        if not self.experimental_mode:
            return

        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "trace_id": self.trace_id,
            "event": event_type,
            "message": message,
            "data": data or {}
        }
        self.execution_log.append(log_entry)

        # Print if experimental mode (for visibility)
        log_format = f"[{timestamp}] [TRACE:{self.trace_id}] [{event_type}] {message}"
        print(log_format)

    def execute(self, task: str) -> dict:
        """
        Intelligently analyze task and spawn appropriate agents.

        Args:
            task: Description of task to complete

        Returns:
            Workflow with appropriate spawned agents
        """
        self._log_event("EXECUTE", f"Task received: {task}")

        # Step 1: Classify the task
        task_type = self._classify_task(task)
        self._log_event("CLASSIFY", f"Task classified as: {task_type}")

        # Step 2: Plan based on task type
        plan = self.thought_tool.plan(task)
        self._log_event("PLAN", "Planning complete", {"task_type": task_type})

        # Step 3: Determine agents needed
        agents_needed = self._determine_agents(task_type, task)
        self._log_event("AGENTS_DETERMINED", f"Agents needed: {agents_needed}")

        # Step 4: Build workflow
        workflow = self._build_workflow(task, task_type, agents_needed, plan)
        self._log_event("WORKFLOW_BUILT", "Workflow construction complete")

        # Add experimental metadata to workflow
        if self.experimental_mode:
            workflow["trace_id"] = self.trace_id
            workflow["execution_log"] = self.execution_log
            workflow["experimental_mode"] = True

        return workflow

    def _classify_task(self, task: str) -> str:
        """
        Classify task type based on keywords.

        Args:
            task: Task description

        Returns:
            Task type: security, bug_analysis, performance, quality, data_operations, or general
        """
        task_lower = task.lower()

        for task_type, keywords in self.TASK_PATTERNS.items():
            if any(keyword in task_lower for keyword in keywords):
                return task_type

        return "general"

    def _determine_agents(self, task_type: str, task: str) -> list:
        """
        Determine which agents are needed based on task type.

        Args:
            task_type: Type of task (security, bug_analysis, etc.)
            task: Task description

        Returns:
            List of agents to spawn
        """
        agents = []

        if task_type == "security":
            agents = ["diagnostician", "reviewer"]

        elif task_type == "bug_analysis":
            agents = ["diagnostician", "bug_fixer", "reviewer"]

        elif task_type == "performance":
            agents = ["diagnostician", "reviewer"]

        elif task_type == "quality":
            agents = ["diagnostician", "reviewer"]

        elif task_type == "data_operations":
            agents = ["group_sale_manager"]

        else:  # general
            agents = ["diagnostician", "reviewer"]

        return agents

    def _build_workflow(self, task: str, task_type: str, agents_needed: list, thinking: dict) -> dict:
        """
        Build execution workflow with spawned agents.

        Args:
            task: Task description
            task_type: Classified task type
            agents_needed: List of agents to spawn
            thinking: Analysis from thought tool

        Returns:
            Workflow with spawned agents
        """
        workflow_steps = self._create_workflow_steps(task_type, agents_needed)

        return {
            "success": True,
            "agent": "team_leader",
            "task": task,
            "response": f"Team Leader orchestrating {task_type} workflow",
            "thinking": thinking,
            "task_type": task_type,
            "workflow_type": self._get_workflow_name(task_type),
            "workflow_steps": workflow_steps,
            "spawned_agents": [{"agent": agent, "role": self._get_agent_role(agent)} for agent in agents_needed],
            "tools_used": self.tools,
            "status": "ready_to_execute"
        }

    def _create_workflow_steps(self, task_type: str, agents: list) -> list:
        """
        Create workflow steps based on task type and agents.

        Args:
            task_type: Type of task
            agents: List of agents in workflow

        Returns:
            List of workflow steps
        """
        steps = []
        step_num = 1

        # Define step sequences based on agents and task type
        if "diagnostician" in agents:
            steps.append({
                "step": step_num,
                "agent": "diagnostician",
                "task": self._get_diagnostician_task(task_type),
                "focus": self._get_diagnostician_focus(task_type)
            })
            step_num += 1

        if "bug_fixer" in agents and "diagnostician" in agents:
            steps.append({
                "step": step_num,
                "agent": "bug_fixer",
                "task": "Implement fixes for identified issues",
                "focus": ["Apply fixes", "Maintain code quality", "Create commits"]
            })
            step_num += 1

        if "reviewer" in agents:
            steps.append({
                "step": step_num,
                "agent": "reviewer",
                "task": "Review and validate findings/changes",
                "focus": self._get_reviewer_focus(task_type)
            })
            step_num += 1

        if "group_sale_manager" in agents:
            steps.append({
                "step": step_num,
                "agent": "group_sale_manager",
                "task": "Execute data operations",
                "focus": ["Query datasets", "Process data", "Provide results"]
            })
            step_num += 1

        return steps if steps else [{"step": 1, "agent": "diagnostician", "task": "Analyze request"}]

    def _get_workflow_name(self, task_type: str) -> str:
        """Get human-readable workflow name."""
        workflow_names = {
            "security": "Security Analysis Workflow",
            "bug_analysis": "Bug Fix Workflow",
            "performance": "Performance Analysis Workflow",
            "quality": "Quality Review Workflow",
            "data_operations": "Data Operations Workflow",
            "general": "General Analysis Workflow"
        }
        return workflow_names.get(task_type, "General Workflow")

    def _get_agent_role(self, agent: str) -> str:
        """Get role description for agent."""
        roles = {
            "diagnostician": "Issue Scanner & Analyzer",
            "bug_fixer": "Implementation Specialist",
            "reviewer": "Quality Validator",
            "group_sale_manager": "Data Operations Manager"
        }
        return roles.get(agent, "Specialist")

    def _get_diagnostician_task(self, task_type: str) -> str:
        """Get diagnostician task based on task type."""
        tasks = {
            "security": "Scan codebase for security vulnerabilities",
            "bug_analysis": "Analyze code for bugs and issues",
            "performance": "Identify performance bottlenecks",
            "quality": "Review code quality and structure",
            "data_operations": "Prepare data analysis",
            "general": "Analyze codebase for issues"
        }
        return tasks.get(task_type, "Analyze codebase")

    def _get_diagnostician_focus(self, task_type: str) -> list:
        """Get focus areas for diagnostician."""
        focus_areas = {
            "security": [
                "Injection vulnerabilities",
                "Authentication/authorization",
                "Credential exposure",
                "XSS vulnerabilities",
                "CSRF protection",
                "Insecure dependencies",
                "Data leakage",
                "Insecure cryptography"
            ],
            "bug_analysis": [
                "Logic errors",
                "Null pointer exceptions",
                "Type mismatches",
                "Resource leaks",
                "Race conditions",
                "Error handling"
            ],
            "performance": [
                "Slow algorithms",
                "Memory leaks",
                "N+1 queries",
                "Unnecessary copying",
                "Inefficient loops"
            ],
            "quality": [
                "Code structure",
                "Design patterns",
                "Readability",
                "Maintainability",
                "Best practices"
            ],
            "general": [
                "Bugs",
                "Performance issues",
                "Security concerns",
                "Code quality"
            ]
        }
        return focus_areas.get(task_type, ["General analysis"])

    def _get_reviewer_focus(self, task_type: str) -> list:
        """Get focus areas for reviewer."""
        focus_areas = {
            "security": [
                "Verify severity",
                "Check false positives",
                "Prioritize critical issues",
                "Provide remediation"
            ],
            "bug_analysis": [
                "Verify fixes",
                "Check for regressions",
                "Validate solutions",
                "Approve changes"
            ],
            "performance": [
                "Validate improvements",
                "Benchmark results",
                "Check trade-offs"
            ],
            "quality": [
                "Code review",
                "Architecture validation",
                "Standards compliance"
            ],
            "general": [
                "Validate findings",
                "Check quality",
                "Approve results"
            ]
        }
        return focus_areas.get(task_type, ["Validate findings"])

