"""Run state machine for orchestrated execution."""

from .schemas import RunStatus


class RunStateMachine:
    """Manages valid state transitions for a run."""

    TRANSITIONS = {
        RunStatus.PLANNING: [RunStatus.RUNNING, RunStatus.FAILED],
        RunStatus.RUNNING: [RunStatus.PAUSED, RunStatus.SYNTHESIZING, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.PAUSED: [RunStatus.RUNNING, RunStatus.CANCELLED],
        RunStatus.SYNTHESIZING: [RunStatus.COMPLETED, RunStatus.FAILED],
        RunStatus.COMPLETED: [],
        RunStatus.FAILED: [],
        RunStatus.CANCELLED: [],
    }

    def __init__(self, initial_status: RunStatus = RunStatus.PLANNING):
        self.current_status = initial_status
        self.status_history = [initial_status]

    def can_transition(self, target_status: RunStatus) -> bool:
        """Check if transition is allowed."""
        return target_status in self.TRANSITIONS.get(self.current_status, [])

    def transition(self, target_status: RunStatus, reason: str = "") -> bool:
        """Attempt transition; raise if invalid."""
        if not self.can_transition(target_status):
            allowed = self.TRANSITIONS.get(self.current_status, [])
            raise ValueError(
                f"Invalid transition: {self.current_status.value} → {target_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self.current_status = target_status
        self.status_history.append(target_status)
        return True
