"""Guard the direct-scope EXECUTE handoff contract."""

import inspect

from claude.system.merchant_runtime_handoff import (
    invoke_authorized_scope_apply,
)


def test_direct_scope_handoff_uses_execute_not_apply():
    source = inspect.getsource(invoke_authorized_scope_apply)

    assert '"--execute"' in source
    assert '"--apply"' not in source
    assert '"--proposal-hash"' not in source
