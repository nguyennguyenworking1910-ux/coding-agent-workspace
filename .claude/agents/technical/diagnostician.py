"""Diagnostician Agent - Analyzes code and finds issues."""

import re
from pathlib import Path
from ..base_agent import BaseAgent


class DiagnosticianAgent(BaseAgent):
    """Analyzer agent that finds bugs and issues."""

    def __init__(self):
        super().__init__("diagnostician", "analyzer", "read-only", ["grep", "read", "glob"])

    def _analyze_python_files(self) -> list:
        """Analyze Python files for common issues."""
        findings = []
        project_root = Path(__file__).parent.parent.parent.parent

        all_files = list(project_root.glob("**/*.py"))
        py_files = [f for f in all_files if "agent_runners" not in str(f) and "__pycache__" not in str(f)]

        print(f"[SCAN_START] Scanning {min(len(py_files), 10)} Python files")

        for idx, py_file in enumerate(py_files[:10], 1):
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                relative_path = str(py_file.relative_to(project_root))

                if re.search(r'(password|api_key|secret|token)\s*=\s*["\']', content, re.IGNORECASE):
                    finding = {
                        "file": relative_path,
                        "issue": "Hardcoded credentials detected",
                        "severity": "CRITICAL"
                    }
                    findings.append(finding)
                    print(f"[!] CRITICAL: {finding['issue']} in {relative_path}")

                if re.search(r'except\s*:', content):
                    finding = {
                        "file": relative_path,
                        "issue": "Bare exception handler found",
                        "severity": "HIGH"
                    }
                    findings.append(finding)
                    print(f"[!] HIGH: {finding['issue']} in {relative_path}")

                if re.search(r'def\s+\w+\([^)]*\):\s*(?!""")', content):
                    finding = {
                        "file": relative_path,
                        "issue": "Function missing docstring",
                        "severity": "MEDIUM"
                    }
                    findings.append(finding)
                    print(f"[!] MEDIUM: {finding['issue']} in {relative_path}")

            except Exception as e:
                print(f"[ERROR] Error scanning {py_file.name}: {str(e)}")

        print(f"[ANALYSIS COMPLETE] Found {len(findings)} issues")
        return findings

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Analyze code and find issues.

        Args:
            task: Analysis task description
            run_id: Unique run ID

        Returns:
            Analysis results
        """
        self._print_header(task, run_id)

        print("[i] [DIAGNOSTICIAN] Agent initialized")
        findings = self._analyze_python_files()
        print(f"[i] [DIAGNOSTICIAN] Analysis complete. Found {len(findings)} issues")

        self._print_footer()

        return self._agent_result(
            success=True,
            task=task,
            response=f"Code analysis complete. Found {len(findings)} issues.",
            thinking="Analyzed Python files for security issues, error handling, and code quality.",
            findings=findings,
            tools_used=self.tools,
            status="analysis_complete",
        )
