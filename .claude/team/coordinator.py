"""Coordinator for managing run lifecycle and task execution."""

import time
from typing import Optional, Dict
from datetime import datetime

from .schemas import (
    AgentPlan,
    RunStatus,
    RunContext,
    TaskStatus,
    AgentEvent,
)
from .state_machine import RunStateMachine
from .run_store import RunStore
from .event_bus import EventBus
from .fake_worker import FakeWorker


class Coordinator:
    """Manages run state machine, task execution, and synthesis."""

    def __init__(self, run_id: str, workspace_dir: str = ".agent-workspace"):
        self.run_id = run_id
        self.store = RunStore(workspace_dir)
        self.event_bus = EventBus()
        self.state_machine = RunStateMachine()
        self.plan: Optional[AgentPlan] = None
        self.workers: Dict[str, FakeWorker] = {}
        self.task_statuses: Dict[str, TaskStatus] = {}
        self.request: str = ""

        # Subscribe to events
        self.event_bus.subscribe_all(self._on_event)

    def _on_event(self, event: AgentEvent) -> None:
        """Handle any event: update task status and persist."""
        # Persist event
        self.store.append_event(self.run_id, event)

        # Update task status
        if event.task_id:
            if event.event_type == "task_completed":
                self.task_statuses[event.task_id] = TaskStatus.COMPLETED
            elif event.event_type == "task_failed":
                self.task_statuses[event.task_id] = TaskStatus.FAILED
            elif event.event_type == "agent_started":
                self.task_statuses[event.task_id] = TaskStatus.RUNNING

    def execute_run(
        self,
        request: str,
        plan: AgentPlan,
        use_fake_workers: bool = True,
        timeout: float = 30.0,
    ) -> bool:
        """Execute a run: planning → running → synthesizing → completed/failed."""
        self.request = request
        self.plan = plan

        # Create run directory
        self.store.create_run_dir(self.run_id)
        self.store.save_request(self.run_id, request)
        self.store.save_plan(self.run_id, plan)

        try:
            # Initialize task statuses
            for task in plan.tasks:
                self.task_statuses[task.task_id] = TaskStatus.PENDING

            # PLANNING phase
            self.state_machine.transition(RunStatus.RUNNING, "Plan validated")
            self._save_status()
            print(f"[COORDINATOR] Plan: {plan.summary}")
            print(f"[COORDINATOR] Workers: {len(plan.agents)}")
            print(f"[COORDINATOR] Tasks: {len(plan.tasks)}")

            # RUNNING phase: execute workers
            if use_fake_workers:
                self._execute_with_fake_workers()
            else:
                self._execute_with_real_workers()

            # Wait for required dependencies
            if not self._wait_for_dependencies(timeout=timeout):
                print("[COORDINATOR] Dependency timeout")
                self.state_machine.transition(RunStatus.FAILED, "Dependency timeout")
                self._save_status()
                return False

            # SYNTHESIZING phase
            self.state_machine.transition(RunStatus.SYNTHESIZING, "All dependencies met")
            self._save_status()
            print("[COORDINATOR] Synthesizing results...")

            # Synthesis (lead's job)
            synthesis_response = self._synthesize()
            self.store.save_final_response(self.run_id, synthesis_response)

            # COMPLETED phase
            self.state_machine.transition(RunStatus.COMPLETED, "Synthesis done")
            self._save_status()
            print(f"[COORDINATOR] Run completed: {self.run_id}")

            return True
        except Exception as e:
            print(f"[COORDINATOR] Error: {e}")
            self.state_machine.transition(RunStatus.FAILED, str(e))
            self._save_status()
            return False

    def _execute_with_fake_workers(self) -> None:
        """Start fake workers for all non-lead tasks."""
        for task in self.plan.tasks:
            if task.owner_agent_id == "lead":
                continue  # Lead doesn't run as worker in Milestone 1

            # Create fake worker with staggered delays to test out-of-order completion
            delay = 0.3 + (len(self.workers) * 0.2)  # Stagger delays
            worker = FakeWorker(
                agent_id=task.owner_agent_id,
                task=task,
                run_id=self.run_id,
                delay_seconds=delay,
                fail=False,
                on_event=self.event_bus.publish,
            )
            worker.start()
            self.workers[task.owner_agent_id] = worker
            self.task_statuses[task.task_id] = TaskStatus.RUNNING
            print(f"[COORDINATOR] Started worker: {task.owner_agent_id} (delay: {delay}s)")

    def _wait_for_dependencies(self, timeout: float = 30.0) -> bool:
        """Block until all non-lead tasks complete or timeout."""
        start = time.time()

        while time.time() - start < timeout:
            all_done = True
            for worker in self.workers.values():
                if not worker.thread or worker.thread.is_alive():
                    all_done = False
                    break

            if all_done:
                print("[COORDINATOR] All workers completed")
                return True
            time.sleep(0.1)

        return False

    def _synthesize(self) -> str:
        """Lead synthesizes results from all workers."""
        response = f"# Synthesis for Run {self.run_id}\n\n"
        response += f"**Request:** {self.request}\n\n"
        response += f"**Plan:** {self.plan.summary}\n\n"

        completed = sum(
            1
            for status in self.task_statuses.values()
            if status == TaskStatus.COMPLETED
        )
        failed = sum(
            1 for status in self.task_statuses.values() if status == TaskStatus.FAILED
        )

        response += f"## Results\n"
        response += f"- Tasks completed: {completed}\n"
        response += f"- Tasks failed: {failed}\n"
        response += f"- Total tasks: {len(self.task_statuses)}\n"

        # List worker findings
        if self.plan.agents:
            response += f"\n## Worker Findings\n"
            for agent in self.plan.agents:
                status = "[OK]" if agent.agent_id in self.workers else "[--]"
                response += f"- {status} {agent.agent_id.title()} ({agent.role.value})\n"

        response += f"\n---\n*Generated at {datetime.utcnow().isoformat()}*\n"
        return response

    def _save_status(self) -> None:
        """Save current run status."""
        context = RunContext(
            run_id=self.run_id,
            request=self.request,
            status=self.state_machine.current_status,
            plan=self.plan,
        )
        self.store.save_status(self.run_id, context)

    def _execute_with_real_workers(self) -> None:
        """Placeholder for Milestone 2 real Claude workers."""
        raise NotImplementedError("Real workers in Milestone 2")
