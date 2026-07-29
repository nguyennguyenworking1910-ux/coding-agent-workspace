"""Multi-Terminal Orchestrator - Runs agents in separate terminals."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from .terminal_manager import TerminalManager
from .technical import get_technical_agent
from config import get_config


class MultiTerminalOrchestrator:
    """Orchestrates agent execution across multiple terminals."""

    # Task classification
    TASK_PATTERNS = {
        "bug_analysis": [
            "bug", "error", "issue", "problem", "crash", "broken", "fail",
            "exception", "debug", "diagnose", "analyze code"
        ],
        "quality": [
            "quality", "review", "validate", "check", "test", "refactor",
            "structure", "design", "architecture"
        ],
    }

    def __init__(self, use_multi_terminal: bool = True, use_vscode_terminal: bool = False):
        """Initialize orchestrator.

        Args:
            use_multi_terminal: Whether to use separate terminals
            use_vscode_terminal: Whether to use VS Code integrated terminal
        """
        self.name = "multi_terminal_orchestrator"
        self.use_multi_terminal = use_multi_terminal
        self.use_vscode_terminal = use_vscode_terminal
        self.trace_id = str(uuid.uuid4())[:8]
        self.config = get_config()
        self.terminal_manager = TerminalManager(use_vscode_terminal=use_vscode_terminal)
        self.execution_log: List[Dict] = []

    def _log_event(self, event_type: str, message: str, data: Dict = None):
        """Log execution event.

        Args:
            event_type: Type of event (INIT, SPAWN, COMPLETE, etc)
            message: Event description
            data: Optional event data
        """
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "trace_id": self.trace_id,
            "event": event_type,
            "message": message,
            "data": data or {}
        }
        self.execution_log.append(log_entry)
        print(f"[{timestamp}] [{event_type}] {message}")

    def classify_task(self, task: str) -> str:
        """Classify task type based on keywords.

        Args:
            task: Task description

        Returns:
            Task type classification
        """
        task_lower = task.lower()
        for task_type, keywords in self.TASK_PATTERNS.items():
            if any(kw in task_lower for kw in keywords):
                return task_type
        return "general"

    def execute_multi_terminal(self, task: str) -> Dict[str, Any]:
        """Execute task with agents in separate terminals.

        Args:
            task: Task description

        Returns:
            Execution results
        """
        run_id = str(uuid.uuid4())[:8]
        self._log_event("START", f"Multi-terminal execution started", {"task": task, "run_id": run_id})

        # Classify task
        task_type = self.classify_task(task)
        self._log_event("CLASSIFY", f"Task classified as: {task_type}")

        # Determine workflow based on task type
        if task_type == "bug_analysis":
            agents_to_spawn = ["diagnostician", "bug_fixer", "reviewer"]
        elif task_type == "quality":
            agents_to_spawn = ["diagnostician", "reviewer"]
        else:
            agents_to_spawn = ["diagnostician"]

        self._log_event("PLAN", f"Spawning agents: {', '.join(agents_to_spawn)}")

        # Spawn terminals for each agent
        spawned_agents = []
        for agent_name in agents_to_spawn:
            self._log_event("SPAWN", f"Spawning {agent_name} in terminal")

            if self.use_multi_terminal:
                success = self.terminal_manager.spawn_terminal(agent_name, task, run_id)
            else:
                success = self._execute_agent_inline(agent_name, task)

            if success:
                spawned_agents.append(agent_name)
                self._log_event("SPAWNED", f"{agent_name} spawned successfully")
            else:
                self._log_event("ERROR", f"Failed to spawn {agent_name}")

        # Wait for agents to complete
        self._log_event("WAIT", f"Waiting for {len(spawned_agents)} agents to complete")
        print("\n" + "="*70)
        print("MULTI-TERMINAL EXECUTION")
        print("="*70)
        print(f"Run ID: {run_id}")
        print(f"Trace ID: {self.trace_id}")
        print(f"Spawned Agents: {', '.join(spawned_agents)}")
        print("="*70)
        print("\n[OK] Check the open terminals for real-time agent output")
        print("[OK] Each agent is running in its own terminal window\n")

        return {
            "success": True,
            "run_id": run_id,
            "trace_id": self.trace_id,
            "task": task,
            "task_type": task_type,
            "agents_spawned": spawned_agents,
            "execution_log": self.execution_log,
            "mode": "multi-terminal" if self.use_multi_terminal else "inline",
            "status": "agents_spawned"
        }

    def _execute_agent_inline(self, agent_name: str, task: str) -> bool:
        """Execute agent inline (fallback mode).

        Args:
            agent_name: Name of agent to execute
            task: Task description

        Returns:
            True if successful
        """
        try:
            agent_class = get_technical_agent(agent_name)
            if not agent_class:
                return False

            agent = agent_class()
            result = agent.execute(task)
            self._log_event("RESULT", f"{agent_name} completed", result)
            return result.get("success", False)
        except Exception as e:
            self._log_event("ERROR", f"Failed to execute {agent_name}: {e}")
            return False

    def execute(self, task: str) -> Dict[str, Any]:
        """Main execution method.

        Args:
            task: Task description

        Returns:
            Execution results
        """
        self._log_event("INIT", "Multi-Terminal Orchestrator initialized", {"multi_terminal": self.use_multi_terminal})

        result = self.execute_multi_terminal(task)

        self._log_event("COMPLETE", "Execution complete", result)

        # For spawned terminals, don't cleanup immediately - files are needed for execution
        # Scripts will be overwritten on next run anyway
        # Only cleanup for inline execution mode
        if not self.use_multi_terminal:
            self.terminal_manager.cleanup()

        return result
