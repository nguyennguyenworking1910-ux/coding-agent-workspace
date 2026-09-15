---
description: Show or switch this session's Merchant confirmation mode for local development
argument-hint: "on | off | status"
disable-model-invocation: true
---

# Merchant confirmation mode

**Argument:** $ARGUMENTS

This command is handled entirely by the `UserPromptSubmit` hook
(`.claude/hooks/intent_gate.py` → `.claude/hooks/merchant_confirmation_preferences.py`).
The hook applies the mode change and reports the result, so the prompt never reaches
classification, never creates or dispatches a teammate, and never touches Merchant business
data.

| Argument | Effect |
|---|---|
| `on` | MANUAL mode: manual confirmation-token entry is required. Discards any stored proposal receipt. |
| `off` | LOCAL_AUTO mode: manual token copy/paste is disabled for a narrow local-development allowlist. Denied unless every prerequisite holds. |
| `status` | Reports the current mode and whether an unspent proposal receipt exists. |

Anything else — no argument, several arguments, or an unrecognized word — is refused and the
mode is left unchanged.

## What "confirmation off" does and does not mean

`off` disables **manual token copy/paste only**. It does not disable, and cannot disable:

- proposal binding (`proposal_hash`);
- payload hashing (`payload_hash`);
- expected-version checking;
- intent and policy validation;
- one-use authorization and the at-most-once runtime handoff;
- atomic, session-scoped persistence.

In LOCAL_AUTO mode the apply still requires the **exact** operation fields in the request. The
generic `/solve Apply the proposal` is refused; the payload is rebuilt from the request and
compared against the stored confirmation metadata, which holds hashes only and never raw
fields.

## Prerequisites for `off`

All of these must hold, or the mode change is denied and the session stays MANUAL:

- `MERCHANT_ALLOW_LOCAL_AUTO_CONFIRM=1`;
- the configured Merchant host is exactly `127.0.0.1` or `localhost`;
- Claude Code is running interactively;
- a valid session id is present.

## Scope of LOCAL_AUTO

Auto-confirm is allowed only for `project create`, `project update`, and `step update`.
`merchant activate`, `merchant activate-all`, `merchant create`, `contact import`,
`document revision-create`, `document approve`, `procurement update`,
`integration identifier-set`, and every destructive or unknown operation continue to require
the manual confirmation token.

The mode and any receipt are cleared at `SessionEnd`, so every new session starts in MANUAL.

## If you are the model reading this body

The hook did not handle the prompt, which means it is not installed or not running. Report
that the Merchant confirmation toggle is unavailable and stop. Do not change any file, do not
dispatch a teammate, do not run the Merchant CLI, and do not emulate the mode change.

Full documentation: `.claude/documents/MERCHANT_PROJECT_MANAGER.md`, section 21.
