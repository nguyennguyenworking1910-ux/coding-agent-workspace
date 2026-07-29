"""Streaming handler for real-time agent output."""

import sys
import time
from typing import Any, Dict, List, Callable, Optional
from datetime import datetime


class StreamHandler:
    """Handles real-time streaming of agent output."""

    def __init__(self, agent_name: str, task: str, run_id: str):
        """Initialize stream handler.

        Args:
            agent_name: Name of the agent
            task: Task description
            run_id: Unique run ID
        """
        self.agent_name = agent_name
        self.task = task
        self.run_id = run_id
        self.start_time = datetime.now()
        self.events = []

    def stream_header(self):
        """Stream header information."""
        header = f"\n{'='*70}\n"
        header += f"AGENT: {self.agent_name.upper()}\n"
        header += f"RUN ID: {self.run_id}\n"
        header += f"TASK: {self.task}\n"
        header += f"START TIME: {self.start_time.strftime('%H:%M:%S')}\n"
        header += f"{'='*70}\n\n"
        self._print_stream(header)

    def stream_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        """Stream an event with real-time output.

        Args:
            event_type: Type of event (ANALYZING, FINDING, PLANNING, etc.)
            message: Event message
            data: Optional event data
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        event = {
            "timestamp": timestamp,
            "type": event_type,
            "message": message,
            "data": data or {}
        }
        self.events.append(event)

        # Format output
        output = f"[{timestamp}] [{event_type}] {message}\n"
        if data:
            for key, value in data.items():
                output += f"           {key}: {value}\n"

        self._print_stream(output)
        time.sleep(0.1)  # Slight delay for readability

    def stream_finding(self, finding: Dict):
        """Stream a finding with details.

        Args:
            finding: Finding dictionary with file, issue, severity
        """
        output = f"\n[FINDING] Security Issue Detected\n"
        output += f"  File: {finding.get('file', 'unknown')}\n"
        output += f"  Issue: {finding.get('issue', 'unknown')}\n"
        output += f"  Severity: {finding.get('severity', 'UNKNOWN')}\n"
        self._print_stream(output)
        self.stream_event("FINDING", f"{finding.get('issue')}", finding)

    def stream_progress(self, current: int, total: int, message: str = ""):
        """Stream progress update.

        Args:
            current: Current count
            total: Total count
            message: Optional progress message
        """
        percentage = (current / total) * 100 if total > 0 else 0
        progress_bar = f"[{'='*int(percentage/5)}{' '*int((100-percentage)/5)}] {percentage:.0f}%"
        output = f"\r{progress_bar}"
        if message:
            output = f"\n{message} {progress_bar}"
        self._print_stream(output, end="")

    def stream_section(self, title: str, items: List[str]):
        """Stream a section with items.

        Args:
            title: Section title
            items: List of items to display
        """
        output = f"\n[{title}]\n"
        for i, item in enumerate(items, 1):
            output += f"  {i}. {item}\n"
        self._print_stream(output)

    def stream_analysis_result(self, analysis: Dict):
        """Stream analysis results.

        Args:
            analysis: Analysis result dictionary
        """
        output = f"\n[ANALYSIS COMPLETE]\n"
        output += f"  Total Issues Found: {len(analysis.get('findings', []))}\n"
        output += f"  Security Issues: {sum(1 for f in analysis.get('findings', []) if f.get('severity') == 'HIGH' or f.get('severity') == 'CRITICAL')}\n"
        output += f"  Medium Issues: {sum(1 for f in analysis.get('findings', []) if f.get('severity') == 'MEDIUM')}\n"
        output += f"  Low Issues: {sum(1 for f in analysis.get('findings', []) if f.get('severity') == 'LOW')}\n"
        self._print_stream(output)
        self.stream_event("ANALYSIS_COMPLETE", f"Analysis found {len(analysis.get('findings', []))} issues")

    def stream_plan(self, plan: List[Dict]):
        """Stream fix plan.

        Args:
            plan: List of fix strategies
        """
        output = f"\n[FIX PLAN]\n"
        for i, strategy in enumerate(plan, 1):
            output += f"  {i}. {strategy.get('type', 'Unknown').upper()}\n"
            output += f"     {strategy.get('description', 'No description')}\n"
            output += f"     Priority: {strategy.get('priority', 'MEDIUM')}\n\n"
        self._print_stream(output)
        self.stream_event("FIX_PLAN_READY", f"Prepared {len(plan)} fix strategies")

    def stream_validation(self, validation: Dict):
        """Stream validation results.

        Args:
            validation: Validation result dictionary
        """
        output = f"\n[VALIDATION RESULTS]\n"
        passed = 0
        for check, result in validation.items():
            status = "[PASS]" if result.get('passed') else "[FAIL]"
            output += f"  {status} {check.upper()}\n"
            output += f"       {result.get('details', '')}\n\n"
            if result.get('passed'):
                passed += 1

        score = (passed / len(validation)) * 100 if len(validation) > 0 else 0
        approval = "APPROVED" if score >= 80 else "NEEDS_REVIEW"
        output += f"\n[FINAL SCORE] {int(score)}% - {approval}\n"
        self._print_stream(output)
        self.stream_event("VALIDATION_COMPLETE", f"Validation score: {int(score)}%")

    def stream_footer(self):
        """Stream footer with summary."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        footer = f"\n{'='*70}\n"
        footer += f"STATUS: COMPLETED\n"
        footer += f"ELAPSED TIME: {elapsed:.2f} seconds\n"
        footer += f"TOTAL EVENTS: {len(self.events)}\n"
        footer += f"{'='*70}\n"
        footer += f"\nPress ENTER to close this terminal...\n"
        footer += f"{'='*70}\n"
        self._print_stream(footer)

    def stream_team_proposal(self, proposed_agents: List[str]):
        """
        Stream team composition proposal.

        Args:
            proposed_agents: List of proposed agent names
        """
        output = f"\n[TEAM PROPOSAL]\n"
        for agent in proposed_agents:
            output += f"  - {agent.upper()}\n"
        self._print_stream(output)
        self.stream_event("TEAM_PROPOSAL", f"Proposed {len(proposed_agents)} agents")

    def stream_checkpoint(self, message: str):
        """
        Stream a user interaction checkpoint.

        Args:
            message: Checkpoint message
        """
        output = f"\n[CHECKPOINT] {message}\n"
        self._print_stream(output)
        self.stream_event("CHECKPOINT", message)

    def _print_stream(self, message: str, end: str = "\n"):
        """Internal method to print stream output.

        Args:
            message: Message to print
            end: Line ending character
        """
        print(message, end=end, flush=True)
        sys.stdout.flush()

    def get_summary(self) -> Dict:
        """Get event summary.

        Returns:
            Dictionary containing summary of all events
        """
        return {
            "agent": self.agent_name,
            "task": self.task,
            "run_id": self.run_id,
            "start_time": self.start_time.isoformat(),
            "event_count": len(self.events),
            "events": self.events
        }
