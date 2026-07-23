"""Unified Workspace Manager - Handles all workspace operations."""

import json
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


class Workspace:
    """Unified workspace manager for jobs, agents, terminals, and communications."""

    def __init__(self, workspace: str = ".claude-workspace"):
        self.workspace = workspace
        self.jobs_dir = os.path.join(workspace, "jobs")
        self.agents_dir = os.path.join(workspace, "agents")
        self.terminals_dir = os.path.join(workspace, "terminals")
        self.comms_dir = os.path.join(workspace, "communications")

        for directory in [self.jobs_dir, self.agents_dir, self.terminals_dir, self.comms_dir]:
            Path(directory).mkdir(parents=True, exist_ok=True)

        self._init_registries()

    def _init_registries(self):
        """Initialize all registries."""
        for registry_file in [
            os.path.join(self.agents_dir, "registry.json"),
            os.path.join(self.comms_dir, "messages.log")
        ]:
            if not os.path.exists(registry_file):
                if registry_file.endswith(".json"):
                    with open(registry_file, "w") as f:
                        json.dump({"created_at": datetime.now().isoformat(), "agents": {}}, f)
                else:
                    with open(registry_file, "w") as f:
                        f.write("# Communication Log\n\n")

    # ==================== Job Operations ====================

    def create_job(self, title: str, description: str, subtasks: List[str] = None) -> str:
        """Create a new job.

        Args:
            title: Job title
            description: Job description
            subtasks: List of subtasks

        Returns:
            Job ID
        """
        job_id = f"job-{str(uuid.uuid4())[:12]}"
        job_path = os.path.join(self.jobs_dir, job_id)
        Path(job_path).mkdir(parents=True, exist_ok=True)
        Path(os.path.join(job_path, "OUTPUT")).mkdir(exist_ok=True)

        context = f"# {title}\n\n{description}\n\nCreated: {datetime.now().isoformat()}\n"
        if subtasks:
            context += "\n## Subtasks\n"
            for i, task in enumerate(subtasks, 1):
                context += f"- [{i}] {task}\n"

        try:
            with open(os.path.join(job_path, "CONTEXT.md"), "w") as f:
                f.write(context)

            with open(os.path.join(job_path, "STATUS.md"), "w") as f:
                f.write(f"# Status: CREATED\n\nStarted: {datetime.now().isoformat()}\n")
        except (IOError, OSError) as e:
            logger.error(f"Failed to create job {job_id}: {e}")
            raise

        return job_id

    def get_job(self, job_id: str) -> Optional[str]:
        """Get job context.

        Args:
            job_id: Job ID

        Returns:
            Job context or None
        """
        context_file = os.path.join(self.jobs_dir, job_id, "CONTEXT.md")
        if os.path.exists(context_file):
            try:
                with open(context_file) as f:
                    return f.read()
            except IOError as e:
                logger.error(f"Failed to read job context {job_id}: {e}")
                return None
        return None

    def list_jobs(self) -> List[str]:
        """List all jobs.

        Returns:
            List of job IDs
        """
        if not os.path.exists(self.jobs_dir):
            return []
        return [d for d in os.listdir(self.jobs_dir) if os.path.isdir(os.path.join(self.jobs_dir, d))]

    # ==================== Agent Operations ====================

    def spawn_agent(self, job_id: str, task: str, agent_type: str = "worker") -> Tuple[str, Dict]:
        """Spawn a new agent.

        Args:
            job_id: Job ID
            task: Task description
            agent_type: Agent type

        Returns:
            Tuple of (agent_id, agent_record)
        """
        agent_id = f"agent-{str(uuid.uuid4())[:12]}"

        agent = {
            "id": agent_id,
            "job_id": job_id,
            "type": agent_type,
            "task": task,
            "status": "pending",
            "spawned_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "tokens": {"input": 0, "output": 0},
            "error": None
        }

        agent_file = os.path.join(self.agents_dir, f"{agent_id}.json")
        try:
            with open(agent_file, "w") as f:
                json.dump(agent, f, indent=2)
        except (IOError, OSError) as e:
            logger.error(f"Failed to create agent {agent_id}: {e}")
            raise

        self._update_registry(agent_id, job_id, agent_type)
        return agent_id, agent

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """Get agent record.

        Args:
            agent_id: Agent ID

        Returns:
            Agent record or None
        """
        agent_file = os.path.join(self.agents_dir, f"{agent_id}.json")
        if os.path.exists(agent_file):
            try:
                with open(agent_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load agent {agent_id}: {e}")
                return None
        return None

    def update_agent(self, agent_id: str, **kwargs) -> bool:
        """Update agent record.

        Args:
            agent_id: Agent ID
            **kwargs: Fields to update

        Returns:
            True if updated
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False

        agent.update(kwargs)
        agent_file = os.path.join(self.agents_dir, f"{agent_id}.json")
        try:
            with open(agent_file, "w") as f:
                json.dump(agent, f, indent=2)
            return True
        except (IOError, OSError) as e:
            logger.error(f"Failed to update agent {agent_id}: {e}")
            return False

    def list_agents(self, job_id: str = None) -> List[Dict]:
        """List agents.

        Args:
            job_id: Optional filter by job ID

        Returns:
            List of agents
        """
        agents = []
        if not os.path.exists(self.agents_dir):
            return agents

        for file in os.listdir(self.agents_dir):
            if file.endswith(".json") and file != "registry.json":
                try:
                    with open(os.path.join(self.agents_dir, file)) as f:
                        agent = json.load(f)
                        if job_id is None or agent["job_id"] == job_id:
                            agents.append(agent)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Failed to load agent from {file}: {e}")
                    continue
        return agents

    def get_job_agents(self, job_id: str) -> List[Dict]:
        """Get agents for a job.

        Args:
            job_id: Job ID

        Returns:
            List of agents
        """
        return self.list_agents(job_id=job_id)

    # ==================== Terminal Operations ====================

    def register_terminal(self, agent_id: str, job_id: str, task: str) -> Dict:
        """Register a terminal.

        Args:
            agent_id: Agent ID
            job_id: Job ID
            task: Task description

        Returns:
            Terminal record
        """
        terminal = {
            "agent_id": agent_id,
            "job_id": job_id,
            "task": task,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None
        }

        terminal_file = os.path.join(self.terminals_dir, f"{agent_id}.json")
        try:
            with open(terminal_file, "w") as f:
                json.dump(terminal, f, indent=2)
        except (IOError, OSError) as e:
            logger.error(f"Failed to register terminal {agent_id}: {e}")
            raise

        return terminal

    def get_terminal(self, agent_id: str) -> Optional[Dict]:
        """Get terminal.

        Args:
            agent_id: Agent ID

        Returns:
            Terminal record or None
        """
        terminal_file = os.path.join(self.terminals_dir, f"{agent_id}.json")
        if os.path.exists(terminal_file):
            try:
                with open(terminal_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load terminal {agent_id}: {e}")
                return None
        return None

    def update_terminal(self, agent_id: str, **kwargs) -> bool:
        """Update terminal.

        Args:
            agent_id: Agent ID
            **kwargs: Fields to update

        Returns:
            True if updated
        """
        terminal = self.get_terminal(agent_id)
        if not terminal:
            return False

        terminal.update(kwargs)
        terminal_file = os.path.join(self.terminals_dir, f"{agent_id}.json")
        try:
            with open(terminal_file, "w") as f:
                json.dump(terminal, f, indent=2)
            return True
        except (IOError, OSError) as e:
            logger.error(f"Failed to update terminal {agent_id}: {e}")
            return False

    def get_job_terminals(self, job_id: str) -> List[Dict]:
        """Get terminals for a job.

        Args:
            job_id: Job ID

        Returns:
            List of terminals
        """
        terminals = []
        if not os.path.exists(self.terminals_dir):
            return terminals

        for file in os.listdir(self.terminals_dir):
            if file.endswith(".json"):
                try:
                    with open(os.path.join(self.terminals_dir, file)) as f:
                        terminal = json.load(f)
                        if terminal["job_id"] == job_id:
                            terminals.append(terminal)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Failed to load terminal from {file}: {e}")
                    continue

        return terminals

    # ==================== Communication Operations ====================

    def send_message(self, from_id: str, to_id: str, message: str, job_id: str) -> None:
        """Send message between agents.

        Args:
            from_id: Sender ID
            to_id: Recipient ID
            message: Message content
            job_id: Job ID
        """
        timestamp = datetime.now().isoformat()

        with open(os.path.join(self.comms_dir, "messages.log"), "a") as f:
            f.write(f"[{timestamp}] {from_id} -> {to_id}: {message[:80]}\n")

        job_comms = os.path.join(self.comms_dir, job_id)
        Path(job_comms).mkdir(exist_ok=True)

        msg_file = os.path.join(job_comms, f"{from_id}-to-{to_id}.md")
        with open(msg_file, "a") as f:
            f.write(f"\n[{timestamp}] {message}\n")

    def get_messages(self, to_id: str, job_id: str) -> str:
        """Get messages for agent.

        Args:
            to_id: Recipient ID
            job_id: Job ID

        Returns:
            Messages content
        """
        job_comms = os.path.join(self.comms_dir, job_id)
        messages = ""

        if not os.path.exists(job_comms):
            return messages

        for file in os.listdir(job_comms):
            if file.endswith(f"-to-{to_id}.md"):
                msg_file = os.path.join(job_comms, file)
                with open(msg_file) as f:
                    messages += f.read()

        return messages

    # ==================== Reporting ====================

    def get_job_progress(self, job_id: str) -> Dict[str, Any]:
        """Get job progress.

        Args:
            job_id: Job ID

        Returns:
            Progress information
        """
        agents = self.get_job_agents(job_id)

        total = len(agents)
        completed = sum(1 for a in agents if a["status"] == "completed")
        running = sum(1 for a in agents if a["status"] == "running")
        failed = sum(1 for a in agents if a["status"] == "failed")

        return {
            "job_id": job_id,
            "total": total,
            "completed": completed,
            "running": running,
            "failed": failed,
            "percentage": (completed / total * 100) if total > 0 else 0,
            "agents": agents
        }

    def get_aggregated_output(self, job_id: str) -> str:
        """Get aggregated output from all agents.

        Args:
            job_id: Job ID

        Returns:
            Aggregated output
        """
        agents = self.get_job_agents(job_id)
        output_dir = os.path.join(self.jobs_dir, job_id, "OUTPUT")

        result = f"# Job {job_id} Results\n\nGenerated: {datetime.now().isoformat()}\n\n"

        for agent in agents:
            agent_id = agent["id"]
            output_file = os.path.join(output_dir, f"{agent_id}.txt")

            result += f"\n## Agent {agent_id}\n"
            result += f"Status: {agent['status']}\n"
            result += f"Task: {agent['task']}\n"

            if os.path.exists(output_file):
                with open(output_file) as f:
                    result += f"\n{f.read()}\n"
            elif agent.get("result"):
                result += f"\n{agent['result']}\n"

        return result

    # ==================== Utility ====================

    def _update_registry(self, agent_id: str, job_id: str, agent_type: str) -> None:
        """Update agent registry."""
        registry_file = os.path.join(self.agents_dir, "registry.json")

        try:
            with open(registry_file) as f:
                registry = json.load(f)

            registry["agents"][agent_id] = {
                "job_id": job_id,
                "type": agent_type,
                "spawned_at": datetime.now().isoformat()
            }

            with open(registry_file, "w") as f:
                json.dump(registry, f, indent=2)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to update registry: {e}")
