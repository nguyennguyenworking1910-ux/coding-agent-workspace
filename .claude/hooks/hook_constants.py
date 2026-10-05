"""Shared constants for hook modules.

Consolidates 30+ repeated string literals used across team_lifecycle,
team_result_hook, policy_gate, and tmux handlers. Reduces duplication,
improves maintainability, enables single-point changes.
"""

# Lifecycle & task state
TEAMMATES = "teammates"
STATUS = "status"
CURRENT_RUN_ID = "current_run_id"
CURRENT_TASK_ID = "current_task_id"
CANONICAL_NAME = "canonical_name"
REPORT_SOURCE = "report_source"
RESULT_RECEIVED = "result_received"
TERMINAL_RECOVERY_SENT = "terminal_recovery_sent"

# Authorization
AUTHORIZED_OPERATIONS = "authorized_operations"
AUTHORIZED_SELECTED_AGENTS = "authorized_selected_agents"
FAILURE_REASON = "failure_reason"

# Lifecycle status values
DOES_NOT_EXIST = "DOES_NOT_EXIST"
NON_CANONICAL = "NON_CANONICAL"
AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
FOUND = "FOUND"

# Tool/Command
AGENT_TYPE = "agent_type"
TOOL_NAME = "tool_name"
TOOL_INPUT = "tool_input"
TOOL_USE_ID = "tool_use_id"
TOOL_RESPONSE = "tool_response"
COMMAND = "command"

# Common tool names
BASH = "Bash"
POWERSHELL = "PowerShell"
SENDMESSAGE = "SendMessage"

# Merchant operations
MERCHANT_READ = "merchant_read"
MERCHANT_PROPOSE = "merchant_propose"
MERCHANT_APPLY = "merchant_apply"
RESOLVE = "resolve"

# Resolution & proposal
RESOLUTION = "resolution"
MERCHANT_ID = "merchant_id"
QUERY = "query"
RESOLVED = "RESOLVED"
STATUS_RESOLVED = "RESOLVED"  # Uppercase status variant
RESULT_LEDGER = "result_ledger"
CONFIRMATION_HASH = "confirmation_hash"

# Entity fields (tmux/gate)
PANE_SESSION_ID = "pane_session_id"
PROJECT_ID = "project_id"
STEP_ID = "step_id"
REVISION_ID = "revision_id"
DOCUMENT_TYPE = "document_type"
REVISION_NUMBER = "revision_number"
SIGNED = "signed"
SUPERSEDED_BY = "superseded_by"
SCOPE = "scope"

# Document resolution scopes
SCOPE_PROJECT = "PROJECT"
SCOPE_MERCHANT = "MERCHANT"

# Stdout marker
STDOUT = "stdout"
PYTHON = "python"

# Contract/runtime
CONTRACT_VERSION = "contract_version"
OPERATION = "operation"
MODE = "mode"
RECEIPT = "receipt"
STATE = "state"
FIELD = "field"
SHA256 = "sha256"
COMMAND_MODE = "command"  # Not to be confused with COMMAND tool input
