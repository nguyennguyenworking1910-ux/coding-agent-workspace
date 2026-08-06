"""Coordinator for managing run lifecycle and task execution."""

import time
from typing import Optional, Dict, Union
from datetime import datetime
from pathlib import Path

from ...system.schemas import (
    AgentPlan,
    RunStatus,
    RunContext,
    TaskStatus,
    AgentEvent,
)
from ...system.state_machine import RunStateMachine
from ...system.run_store import RunStore
from ...system.event_bus import EventBus
from ...system.mailbox_manager import MailboxManager
from ...system.session_manager import SessionManager
from ...system.worktree_manager import WorktreeManager
from ...system.worker import Worker
from ...system.validator import Validator
from .merge_strategy import MergeStrategy


class Coordinator:
    """Manages run state machine, task execution, and synthesis."""

    def __init__(self, run_id: str, workspace_dir: str = ".agent-workspace", repo_path: str = "."):
        self.run_id = run_id
        self.store = RunStore(workspace_dir)
        self.event_bus = EventBus()
        self.state_machine = RunStateMachine()
        self.plan: Optional[AgentPlan] = None
        self.workers: Dict[str, Worker] = {}
        self.task_statuses: Dict[str, TaskStatus] = {}
        self.request: str = ""

        # M5: Session and messaging support
        self.mailbox_mgr = MailboxManager(run_id, self.store)
        self.session_mgr = SessionManager(run_id, self.store, self.event_bus)
        self.paused = False
        self.skip_tasks: set = set()  # Task IDs to skip (already completed)
        self.start_time: Optional[float] = None

        # M6: Worktree isolation support
        self.worktree_mgr = WorktreeManager(repo_path=repo_path)
        self.merge_strategy = MergeStrategy(repo_path, self.worktree_mgr)
        self.validator = Validator(repo_path)
        self.worktree_paths: Dict[str, Path] = {}  # agent_id -> worktree_path
        self.use_worktrees = False  # Will be set by execute_run

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
        use_worktrees: bool = False,
        merge_strategy: str = "auto",
        timeout: float = 30.0,
        resume: bool = False,
    ) -> bool:
        """Execute a run: planning → running → synthesizing → completed/failed.

        Args:
            request: User request
            plan: Execution plan
            use_worktrees: Use git worktrees for isolated agent modifications
            merge_strategy: Merge strategy ("auto" | "manual" | "abort")
            timeout: Timeout for task execution
            resume: Resume from checkpoint if available

        Returns:
            True if successful
        """
        self.request = request
        self.plan = plan
        self.use_worktrees = use_worktrees
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
            # M6: Create worktrees for agents
            if use_worktrees:
                self._create_worktrees(plan)

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
            self._execute_with_real_workers()

            # Wait for required dependencies
            if not self._wait_for_dependencies(timeout=timeout):
                print("[COORDINATOR] Dependency timeout")
                self.state_machine.transition(RunStatus.FAILED, "Dependency timeout")
                self._save_status()
                return False

            # M6: Merge and validate worktree changes
            if use_worktrees:
                if not self._merge_and_validate(merge_strategy):
                    print("[COORDINATOR] Merge failed, aborting run")
                    self.state_machine.transition(RunStatus.FAILED, "Merge failed")
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

    def _enrich_task_with_findings(self, task: "AgentTask") -> "AgentTask":
        """Enrich task instructions with findings from dependent tasks."""
        if not task.depends_on:
            return task

        # For now, don't enrich - just return the task as-is
        # The dependent task output will be available via the store if needed
        return task

    def _create_worktrees(self, plan: AgentPlan) -> None:
        """Create isolated worktree for each agent.

        Args:
            plan: Execution plan
        """
        for agent in plan.agents:
            if agent.agent_id == "lead":
                continue  # Lead works on main branch

            try:
                path = self.worktree_mgr.create_worktree(agent.agent_id, self.run_id)
                self.worktree_paths[agent.agent_id] = path
                print(f"[COORDINATOR] Worktree created for {agent.agent_id}")
            except Exception as e:
                print(f"[COORDINATOR] Failed to create worktree for {agent.agent_id}: {e}")
                raise

    def _merge_and_validate(self, merge_strategy: str = "auto") -> bool:
        """Merge and validate all worktree changes.

        Args:
            merge_strategy: Merge strategy ("auto" | "manual" | "abort")

        Returns:
            True if successful
        """
        if not self.worktree_paths:
            print("[COORDINATOR] No worktrees to merge")
            return True

        print("[COORDINATOR] Starting merge phase...")

        # Create merge plan respecting task dependencies
        agent_deps = self._get_agent_dependencies()
        batches = self.merge_strategy.create_merge_plan(
            list(self.worktree_paths.keys()), agent_deps
        )

        # Validate changes first
        for agent_id in self.worktree_paths:
            result = self.change_validator.validate_worktree(
                agent_id, str(self.worktree_paths[agent_id])
            )
            if not result.passed and result.errors:
                print(f"[VALIDATOR] Errors in {agent_id}:")
                for err in result.errors:
                    print(f"  - {err.error_type}: {err.message}")
                if merge_strategy == "abort":
                    return False

        # Merge batches sequentially
        for batch in batches:
            success = self.merge_strategy.merge_batch_sequentially(batch, merge_strategy)
            if not success:
                print(f"[COORDINATOR] Merge batch {batch.batch_id} failed")
                if merge_strategy == "abort":
                    return False

        # Cleanup worktrees after successful merge
        self.worktree_mgr.cleanup_all_worktrees()
        self.worktree_paths.clear()  # Clear paths dict after cleanup
        print("[COORDINATOR] Merge complete, worktrees cleaned up")
        return True

    def _get_agent_dependencies(self) -> dict:
        """Map agent IDs to their task dependencies.

        Returns:
            Dict mapping agent_id to list of agent_ids they depend on
        """
        agent_deps = {}
        for task in self.plan.tasks:
            if task.owner_agent_id not in agent_deps:
                agent_deps[task.owner_agent_id] = []

            # Find agents that own depended-on tasks
            for dep_task_id in task.depends_on:
                dep_task = next((t for t in self.plan.tasks if t.task_id == dep_task_id), None)
                if dep_task and dep_task.owner_agent_id != task.owner_agent_id:
                    agent_deps[task.owner_agent_id].append(dep_task.owner_agent_id)

        return agent_deps

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

            # Wait for task dependencies to complete
            if task.depends_on:
                for dep_task_id in task.depends_on:
                    while self.task_statuses.get(dep_task_id) != TaskStatus.COMPLETED:
                        time.sleep(0.1)

            # Enrich task instructions with outputs from dependent tasks
            enriched_task = self._enrich_task_with_findings(task)

            # M6: Use worktree path if available, otherwise current directory
            worktree_path = self.worktree_paths.get(task.owner_agent_id)
            cwd = str(worktree_path) if worktree_path else None

            # Create worker
            worker = Worker(name=task.owner_agent_id)
            self.workers[task.owner_agent_id] = worker
            self.task_statuses[task.task_id] = TaskStatus.RUNNING
            print(f"[COORDINATOR] Started real worker: {task.owner_agent_id}")
