"""Session management for pause/resume capability."""

from typing import Optional, List
from datetime import datetime

from .schemas import CheckpointData, RunStatusSnapshot, RunStatus, TaskStatus
from .run_store import RunStore
from .event_bus import EventBus


class SessionManager:
    """Manages session lifecycle, pause/resume, and checkpoints."""

    def __init__(self, run_id: str, store: RunStore, event_bus: Optional[EventBus] = None):
        """Initialize session manager.

        Args:
            run_id: Run identifier
            store: RunStore for persistence
            event_bus: Optional EventBus for events
        """
        self.run_id = run_id
        self.store = store
        self.event_bus = event_bus

    def save_checkpoint(
        self,
        status: RunStatus,
        completed_task_ids: List[str],
        pending_task_ids: List[str],
        worker_count: int,
        plan_summary: str,
    ) -> bool:
        """Save execution checkpoint.

        Args:
            status: Current run status
            completed_task_ids: List of completed task IDs
            pending_task_ids: List of pending task IDs
            worker_count: Number of workers
            plan_summary: Plan summary string

        Returns:
            True if successful
        """
        try:
            checkpoint = CheckpointData(
                run_id=self.run_id,
                status=status,
                completed_task_ids=completed_task_ids,
                pending_task_ids=pending_task_ids,
                worker_count=worker_count,
                plan_summary=plan_summary,
            )

            self.store.save_checkpoint(self.run_id, checkpoint)
            self.store.save_completed_tasks(self.run_id, completed_task_ids)

            return True
        except Exception as e:
            print(f"[SESSION] Failed to save checkpoint: {e}")
            return False

    def load_checkpoint(self) -> Optional[CheckpointData]:
        """Load execution checkpoint.

        Returns:
            CheckpointData or None if not found
        """
        try:
            return self.store.load_checkpoint(self.run_id)
        except Exception as e:
            print(f"[SESSION] Failed to load checkpoint: {e}")
            return None

    def get_completed_tasks(self) -> List[str]:
        """Get list of completed task IDs.

        Returns:
            List of task IDs
        """
        return self.store.load_completed_tasks(self.run_id)

    def is_resumable(self) -> bool:
        """Check if run can be resumed.

        Returns:
            True if checkpoint exists and run was paused
        """
        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            return False
        return checkpoint.status == RunStatus.PAUSED

    def can_resume_from(self, status: RunStatus) -> bool:
        """Check if run can be resumed from current status.

        Args:
            status: Current run status

        Returns:
            True if status allows resumption
        """
        return status in (RunStatus.PAUSED, RunStatus.RUNNING)

    def get_run_status_snapshot(
        self,
        current_status: RunStatus,
        total_tasks: int,
        task_statuses: dict,
        mailbox_unread: dict,
        start_time: Optional[float] = None,
    ) -> RunStatusSnapshot:
        """Get snapshot of current run status.

        Args:
            current_status: Current run status
            total_tasks: Total task count
            task_statuses: Dict of task_id -> TaskStatus
            mailbox_unread: Dict of agent_id -> unread_count
            start_time: Optional start time for uptime calculation

        Returns:
            RunStatusSnapshot
        """
        completed = sum(1 for s in task_statuses.values() if s == TaskStatus.COMPLETED)
        failed = sum(1 for s in task_statuses.values() if s == TaskStatus.FAILED)
        running = sum(1 for s in task_statuses.values() if s == TaskStatus.RUNNING)
        pending = sum(1 for s in task_statuses.values() if s == TaskStatus.PENDING)

        uptime = 0.0
        if start_time is not None:
            uptime = datetime.utcnow().timestamp() - start_time

        return RunStatusSnapshot(
            run_id=self.run_id,
            current_status=current_status,
            total_tasks=total_tasks,
            completed_tasks=completed,
            pending_tasks=pending,
            running_tasks=running,
            failed_tasks=failed,
            unread_messages=mailbox_unread,
            uptime_seconds=uptime,
        )

    def mark_task_completed(self, task_id: str, completed_task_ids: List[str]) -> None:
        """Mark a task as completed and save to store.

        Args:
            task_id: Task ID
            completed_task_ids: Updated list of completed tasks
        """
        try:
            self.store.save_completed_tasks(self.run_id, completed_task_ids)
        except Exception as e:
            print(f"[SESSION] Failed to mark task {task_id} as completed: {e}")

    def emit_session_event(self, event_type: str, payload: dict) -> None:
        """Emit session-related event.

        Args:
            event_type: Type of event (e.g., "run_paused", "run_resumed")
            payload: Event payload
        """
        if self.event_bus is None:
            return

        import uuid
        from .schemas import AgentEvent

        event = AgentEvent(
            event_id=str(uuid.uuid4())[:8],
            run_id=self.run_id,
            agent_id="system",
            timestamp=datetime.utcnow().isoformat(),
            event_type=event_type,
            payload=payload,
        )

        self.event_bus.publish(event)
