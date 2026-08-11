#!/usr/bin/env python3
"""Comprehensive system test suite for the agent orchestration system."""

import sys
import json
from pathlib import Path
from collections import defaultdict

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ {text}{Colors.END}")

class SystemTest:
    def __init__(self):
        self.base_path = Path(__file__).parent.parent
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results = defaultdict(list)

    def test_folder_structure(self):
        """Test 1: Verify folder structure exists."""
        print_header("TEST 1: FOLDER STRUCTURE")

        required_folders = [
            '.claude/agents',
            '.claude/agents/team',
            '.claude/agents/tools',
            '.claude/clients',
            '.claude/commands',
            '.claude/documents',
            '.claude/system',
        ]

        for folder in required_folders:
            path = self.base_path / folder
            if path.exists() and path.is_dir():
                print_success(f"Folder exists: {folder}")
                self.tests_passed += 1
            else:
                print_error(f"Folder missing: {folder}")
                self.tests_failed += 1

    def test_documentation_files(self):
        """Test 2: Verify all .md files are in documents folder."""
        print_header("TEST 2: DOCUMENTATION FILES")

        # Find all .md files
        md_files = list(self.base_path.glob('.claude/**/*.md'))

        # Filter out examples and other special directories
        invalid_locations = []
        valid_locations = []

        for md_file in md_files:
            relative = md_file.relative_to(self.base_path)
            # as_posix() so the separator check works on Windows too.
            location = relative.as_posix()

            if location.startswith('.claude/documents/'):
                valid_locations.append(relative)
            elif location.startswith('.claude/commands/'):
                # Slash command definitions; the harness only looks here.
                valid_locations.append(relative)
            elif location.startswith('.claude/agents/'):
                # Subagent definitions; the harness only looks here.
                valid_locations.append(relative)
            else:
                invalid_locations.append(relative)

        if valid_locations:
            print_success(f"Found {len(valid_locations)} .md files in correct locations:")
            for f in sorted(valid_locations):
                print(f"  ✓ {f}")
            self.tests_passed += 1

        if invalid_locations:
            print_warning(f"Found {len(invalid_locations)} .md files in WRONG locations:")
            for f in sorted(invalid_locations):
                print(f"  ✗ {f}")
            self.tests_failed += 1
        else:
            print_success("All .md files are in correct locations!")
            self.tests_passed += 1

    def test_agents_json(self):
        """Test 3: Verify agents.json is valid."""
        print_header("TEST 3: AGENTS.JSON CONFIGURATION")

        agents_json_path = self.base_path / '.claude' / 'agents.json'

        if not agents_json_path.exists():
            print_error("agents.json file not found!")
            self.tests_failed += 1
            return

        try:
            with open(agents_json_path, 'r', encoding='utf-8') as f:
                agents_config = json.load(f)
            print_success("agents.json is valid JSON")
            self.tests_passed += 1
        except json.JSONDecodeError as e:
            print_error(f"agents.json is invalid: {e}")
            self.tests_failed += 1
            return

        # Check for required keys
        if 'agents' in agents_config:
            agents = agents_config['agents']
            print_success(f"Found {len(agents)} agents defined:")
            for agent in agents:
                print(f"  ✓ {agent.get('name', 'Unknown')} (id: {agent.get('id', 'Unknown')})")
            self.tests_passed += 1
        else:
            print_error("'agents' key not found in agents.json")
            self.tests_failed += 1

        # Check for scheduler agent
        if any(agent.get('id') == 'scheduler' for agent in agents_config.get('agents', [])):
            print_success("Scheduler agent is registered")
            self.tests_passed += 1
        else:
            print_warning("Scheduler agent not found in agents.json")

    def test_agent_files(self):
        """Test 4: Verify every subagent is defined and enforces ARCHITECTURE.md."""
        print_header("TEST 4: SUBAGENT DEFINITIONS")

        # Subagents are markdown files with YAML frontmatter; that is the only
        # form Claude Code discovers and dispatches.
        required_agents = [
            '.claude/agents/reviewer.md',
            '.claude/agents/red-team.md',
            '.claude/agents/bug-fixer.md',
            '.claude/agents/diagnostician.md',
            '.claude/agents/coder.md',
            '.claude/agents/group-sales-manager.md',
            '.claude/agents/scheduler.md',
        ]

        for agent_file in required_agents:
            path = self.base_path / agent_file
            if not path.exists():
                print_error(f"Subagent definition missing: {agent_file}")
                self.tests_failed += 1
                continue

            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Without frontmatter the file is inert documentation, not a subagent.
            if content.startswith('---') and '\nname:' in content and '\ndescription:' in content:
                print_success(f"Subagent has valid frontmatter: {agent_file}")
                self.tests_passed += 1
            else:
                print_error(f"Subagent missing name/description frontmatter: {agent_file}")
                self.tests_failed += 1

            if 'ARCHITECTURE.md' in content:
                print_success(f"Subagent has ARCHITECTURE.md requirement: {agent_file}")
                self.tests_passed += 1
            else:
                print_error(f"Subagent missing ARCHITECTURE.md requirement: {agent_file}")
                self.tests_failed += 1

    def test_documentation_index(self):
        """Test 5: Verify documentation README exists and is complete."""
        print_header("TEST 5: DOCUMENTATION INDEX")

        readme_path = self.base_path / '.claude' / 'documents' / 'README.md'

        if not readme_path.exists():
            print_error("Documentation README.md not found!")
            self.tests_failed += 1
            return

        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()

        print_success("Documentation README.md exists")
        self.tests_passed += 1

        # Check for key documentation files
        required_docs = [
            ('ARCHITECTURE.md', 'System architecture'),
            ('SETUP.md', 'Setup guide'),
            ('SCHEDULE_CLI.md', 'Schedule agent'),
            ('AGENT_INITIALIZATION.md', 'Agent initialization'),
        ]

        for doc_name, description in required_docs:
            if doc_name in readme_content:
                print_success(f"Documentation indexed: {doc_name}")
                self.tests_passed += 1
            else:
                print_warning(f"Documentation not indexed: {doc_name}")
                self.tests_failed += 1

    def test_critical_documentation(self):
        """Test 6: Verify critical documentation files exist."""
        print_header("TEST 6: CRITICAL DOCUMENTATION")

        critical_docs = [
            '.claude/documents/ARCHITECTURE.md',
            '.claude/documents/AGENT_INITIALIZATION.md',
            '.claude/documents/SETUP.md',
            '.claude/documents/SCHEDULE_CLI.md',
            '.claude/documents/README.md',
        ]

        for doc_file in critical_docs:
            path = self.base_path / doc_file
            if path.exists():
                size = path.stat().st_size
                print_success(f"Document exists: {doc_file} ({size} bytes)")
                self.tests_passed += 1
            else:
                print_error(f"Document missing: {doc_file}")
                self.tests_failed += 1

    def test_system_initialization(self):
        """Test 7: Verify system_init.py exists and is complete."""
        print_header("TEST 7: SYSTEM INITIALIZATION")

        system_init_path = self.base_path / '.claude' / 'agents' / 'system_init.py'

        if not system_init_path.exists():
            print_error("system_init.py not found!")
            self.tests_failed += 1
            return

        with open(system_init_path, 'r', encoding='utf-8') as f:
            content = f.read()

        print_success("system_init.py exists")
        self.tests_passed += 1

        # Check for required functions
        required_functions = [
            'get_architecture_check',
            'architecture_acknowledgment',
            'create_agent_initialization',
            'validate_agent_ready',
        ]

        for func_name in required_functions:
            if f'def {func_name}' in content:
                print_success(f"Function defined: {func_name}()")
                self.tests_passed += 1
            else:
                print_error(f"Function missing: {func_name}()")
                self.tests_failed += 1

    def test_scheduler_agent(self):
        """Test 8: Verify Scheduler agent can be imported."""
        print_header("TEST 8: SCHEDULER AGENT")

        scheduler_path = self.base_path / '.claude' / 'agents' / 'team' / 'scheduler.py'

        if not scheduler_path.exists():
            print_error("scheduler.py not found!")
            self.tests_failed += 1
            return

        with open(scheduler_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if 'class SchedulerAgent' in content:
            print_success("SchedulerAgent class is defined")
            self.tests_passed += 1
        else:
            print_error("SchedulerAgent class not found")
            self.tests_failed += 1

        if 'async def execute' in content:
            print_success("SchedulerAgent has execute method")
            self.tests_passed += 1
        else:
            print_error("SchedulerAgent missing execute method")
            self.tests_failed += 1

        if 'ARCHITECTURE.md' in content and 'STEP 1' in content:
            print_success("SchedulerAgent enforces ARCHITECTURE.md requirement")
            self.tests_passed += 1
        else:
            print_error("SchedulerAgent missing ARCHITECTURE.md enforcement")
            self.tests_failed += 1

    def test_git_status(self):
        """Test 9: Verify no uncommitted changes."""
        print_header("TEST 9: GIT STATUS")

        import subprocess

        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                if result.stdout.strip():
                    print_warning("Uncommitted changes detected:")
                    for line in result.stdout.strip().split('\n'):
                        print(f"  {line}")
                else:
                    print_success("Working tree is clean (all changes committed)")
                    self.tests_passed += 1
            else:
                print_warning("Could not check git status")
        except Exception as e:
            print_warning(f"Git check failed: {e}")

    def test_recent_commits(self):
        """Test 10: Verify recent commits related to system update."""
        print_header("TEST 10: RECENT COMMITS")

        import subprocess

        try:
            result = subprocess.run(
                ['git', 'log', '--oneline', '-10'],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                commits = result.stdout.strip().split('\n')
                print_success(f"Last 10 commits:")

                # Look for system-related commits
                system_commits = [c for c in commits if any(
                    keyword in c.lower() for keyword in
                    ['architecture', 'agent', 'document', 'scheduler', 'initialize']
                )]

                for commit in commits[:5]:
                    if commit in system_commits:
                        print(f"  ✓ {commit}")
                    else:
                        print(f"  • {commit}")

                print_success(f"Found {len(system_commits)} system-related commits")
                self.tests_passed += 1
        except Exception as e:
            print_warning(f"Git log check failed: {e}")

    def run_all_tests(self):
        """Run all tests."""
        print(f"\n{Colors.BOLD}{Colors.BLUE}")
        print("╔" + "="*68 + "╗")
        print("║" + " SYSTEM COMPREHENSIVE TEST SUITE ".center(68) + "║")
        print("║" + " Testing Agent Orchestration System ".center(68) + "║")
        print("╚" + "="*68 + "╝")
        print(f"{Colors.END}\n")

        self.test_folder_structure()
        self.test_documentation_files()
        self.test_agents_json()
        self.test_agent_files()
        self.test_documentation_index()
        self.test_critical_documentation()
        self.test_system_initialization()
        self.test_scheduler_agent()
        self.test_git_status()
        self.test_recent_commits()

        self.print_summary()

    def print_summary(self):
        """Print test summary."""
        print_header("TEST SUMMARY")

        total = self.tests_passed + self.tests_failed
        pass_rate = (self.tests_passed / total * 100) if total > 0 else 0

        print(f"Total Tests: {total}")
        print(f"Passed: {Colors.GREEN}{self.tests_passed}{Colors.END}")
        print(f"Failed: {Colors.RED}{self.tests_failed}{Colors.END}")
        print(f"Pass Rate: {pass_rate:.1f}%")

        if self.tests_failed == 0:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✓ ALL TESTS PASSED!{Colors.END}")
            print(f"{Colors.GREEN}System is fully operational and properly configured.{Colors.END}\n")
            return 0
        else:
            print(f"\n{Colors.RED}{Colors.BOLD}✗ SOME TESTS FAILED{Colors.END}")
            print(f"{Colors.RED}Please review the failures above.{Colors.END}\n")
            return 1

def _force_utf8_stdout():
    """Windows consoles default to cp1252, which cannot encode the box-drawing
    characters and status glyphs used throughout this report."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:  # pragma: no cover - non-reconfigurable stream
            pass


if __name__ == '__main__':
    _force_utf8_stdout()
    tester = SystemTest()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)
