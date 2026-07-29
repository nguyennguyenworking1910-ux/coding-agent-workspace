"""Diagnostician Agent - Analyzes code and finds issues."""

import os
import re
from pathlib import Path
from tools import get_tool
from ..stream_handler import StreamHandler


class DiagnosticianAgent:
    """Analyzer agent that finds bugs and issues."""

    def __init__(self):
        self.name = "diagnostician"
        self.type = "analyzer"
        self.mode = "read-only"
        self.tools = ["grep", "read", "glob"]
        self._init_tools()

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def _analyze_python_files(self, stream: StreamHandler) -> list:
        """Analyze Python files for common issues."""
        findings = []
        project_root = Path(__file__).parent.parent.parent.parent

        # Find Python files
        py_files = list(project_root.glob("**/*.py"))
        total_files = min(len(py_files), 10)

        stream.stream_event("SCAN_START", f"Scanning {total_files} Python files")

        for idx, py_file in enumerate(py_files[:10], 1):
            stream.stream_progress(idx, total_files, f"Analyzing: {py_file.name}")

            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                relative_path = str(py_file.relative_to(project_root))

                # Check for hardcoded credentials
                if re.search(r'(password|api_key|secret|token)\s*=\s*["\']', content, re.IGNORECASE):
                    finding = {
                        "file": relative_path,
                        "issue": "Hardcoded credentials detected",
                        "severity": "CRITICAL"
                    }
                    findings.append(finding)
                    stream.stream_finding(finding)

                # Check for bare exceptions
                if re.search(r'except\s*:', content):
                    finding = {
                        "file": relative_path,
                        "issue": "Bare exception handler found",
                        "severity": "HIGH"
                    }
                    findings.append(finding)
                    stream.stream_finding(finding)

                # Check for missing docstrings in functions
                if re.search(r'def\s+\w+\([^)]*\):\s*(?!""")', content):
                    finding = {
                        "file": relative_path,
                        "issue": "Function missing docstring",
                        "severity": "MEDIUM"
                    }
                    findings.append(finding)
                    stream.stream_finding(finding)

            except Exception as e:
                stream.stream_event("SCAN_ERROR", f"Error scanning {py_file.name}: {str(e)}")

        stream.stream_analysis_result({"findings": findings})
        return findings

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Analyze code and find issues.

        Args:
            task: Analysis task description
            run_id: Unique run ID for streaming

        Returns:
            Analysis results
        """
        stream = StreamHandler(self.name, task, run_id)
        stream.stream_header()

        stream.stream_event("INIT", "Diagnostician agent initialized")
        findings = self._analyze_python_files(stream)
        stream.stream_event("COMPLETE", f"Analysis complete. Found {len(findings)} issues")
        stream.stream_footer()

        return {
            "success": True,
            "agent": "diagnostician",
            "task": task,
            "response": f"Code analysis complete. Found {len(findings)} issues.",
            "thinking": "Analyzed Python files for security issues, error handling, and code quality.",
            "findings": findings,
            "tools_used": self.tools,
            "status": "analysis_complete",
            "stream": stream.get_summary()
        }
