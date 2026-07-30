"""Coordinator for managing run lifecycle and task execution."""

import time
from typing import Optional, Dict, Union
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
from .real_worker import RealWorker
from .mailbox_manager import MailboxManager
from .session_manager import SessionManager


class Coordinator:
    """Manages run state machine, task execution, and synthesis."""

    def __init__(self, run_id: str, workspace_dir: str = ".agent-workspace"):
        self.run_id = run_id
        self.store = RunStore(workspace_dir)
        self.event_bus = EventBus()
        self.state_machine = RunStateMachine()
        self.plan: Optional[AgentPlan] = None
        self.workers: Dict[str, Union[FakeWorker, RealWorker]] = {}
        self.task_statuses: Dict[str, TaskStatus] = {}
        self.request: str = ""

        # M5: Session and messaging support
        self.mailbox_mgr = MailboxManager(run_id, self.store)
        self.session_mgr = SessionManager(run_id, self.store, self.event_bus)
        self.paused = False
        self.skip_tasks: set = set()  # Task IDs to skip (already completed)
        self.start_time: Optional[float] = None

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
                # M5: Save completed tasks for resume capability
                self.session_mgr.mark_task_completed(
                    event.task_id,
                    [
                        task_id
                        for task_id, status in self.task_statuses.items()
                        if status == TaskStatus.COMPLETED
                    ],
                )
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
        resume: bool = False,
    ) -> bool:
        """Execute a run: planning → running → synthesizing → completed/failed.

        Args:
            request: User request
            plan: Execution plan
            use_fake_workers: Use fake workers for testing
            timeout: Timeout for task execution
            resume: Resume from checkpoint if available

        Returns:
            True if successful
        """
        self.request = request
        self.plan = plan
        self.start_time = time.time()

        # Create run directory
        self.store.create_run_dir(self.run_id)
        self.store.save_request(self.run_id, request)
        self.store.save_plan(self.run_id, plan)

        # M5: Try to resume from checkpoint
        if resume and self.session_mgr.is_resumable():
            print(f"[COORDINATOR] Resuming from checkpoint")
            checkpoint = self.session_mgr.load_checkpoint()
            if checkpoint:
                self.skip_tasks = set(checkpoint.completed_task_ids)
                self.mailbox_mgr.load_from_store()
                print(f"[COORDINATOR] Skipping {len(self.skip_tasks)} completed tasks")

        try:
            # Initialize task statuses
            for task in plan.tasks:
                if task.task_id in self.skip_tasks:
                    self.task_statuses[task.task_id] = TaskStatus.COMPLETED
                else:
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
            # M5: Skip already-completed tasks
            if task.task_id in self.skip_tasks:
                print(f"[COORDINATOR] Skipping completed task: {task.task_id}")
                continue

            if task.owner_agent_id == "lead":
                continue  # Lead doesn't run as worker in Milestone 1

            # M5: Check if paused before starting worker
            while self.paused:
                time.sleep(0.1)

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

    def pause(self) -> bool:
        """Pause execution and save checkpoint.

        Returns:
            True if successful
        """
        if self.state_machine.current_status != RunStatus.RUNNING:
            print(f"[COORDINATOR] Cannot pause run with status {self.state_machine.current_status}")
            return False

        self.paused = True
        self.state_machine.transition(RunStatus.PAUSED, "Paused by user")
        self._save_status()
        self._save_checkpoint()
        self.session_mgr.emit_session_event("run_paused", {})
        print(f"[COORDINATOR] Run paused and checkpoint saved")
        return True

    def resume(self) -> bool:
        """Resume execution from pause.

        Returns:
            True if successful
        """
        if self.state_machine.current_status != RunStatus.PAUSED:
            print(f"[COORDINATOR] Cannot resume run with status {self.state_machine.current_status}")
            return False

        self.paused = False
        self.state_machine.transition(RunStatus.RUNNING, "Resumed by user")
        self._save_status()
        self.session_mgr.emit_session_event("run_resumed", {})
        print(f"[COORDINATOR] Run resumed")
        return True

    def _save_checkpoint(self) -> None:
        """Save execution checkpoint for resume capability."""
        completed = [
            task_id
            for task_id, status in self.task_statuses.items()
            if status == TaskStatus.COMPLETED
        ]
        pending = [
            task_id
            for task_id, status in self.task_statuses.items()
            if status in (TaskStatus.PENDING, TaskStatus.BLOCKED)
        ]

        self.session_mgr.save_checkpoint(
            status=self.state_machine.current_status,
            completed_task_ids=completed,
            pending_task_ids=pending,
            worker_count=len(self.plan.agents),
            plan_summary=self.plan.summary,
        )

    def _execute_with_real_workers(self) -> None:
        """Start real Claude workers for all non-lead tasks."""
        for task in self.plan.tasks:
            # M5: Skip already-completed tasks
            if task.task_id in self.skip_tasks:
                print(f"[COORDINATOR] Skipping completed task: {task.task_id}")
                continue

            if task.owner_agent_id == "lead":
                continue  # Lead doesn't run as worker

            # M5: Check if paused before starting worker
            while self.paused:
                time.sleep(0.1)

            # Create real worker
            worker = RealWorker(
                agent_id=task.owner_agent_id,
                task=task,
                run_id=self.run_id,
                cwd=None,  # Use current directory
                timeout=300.0,  # 5 minute timeout
                on_event=self.event_bus.publish,
                store=self.store,  # Pass store for output persistence
            )
            worker.start()
            self.workers[task.owner_agent_id] = worker
            self.task_statuses[task.task_id] = TaskStatus.RUNNING
            print(f"[COORDINATOR] Started real worker: {task.owner_agent_id}")
