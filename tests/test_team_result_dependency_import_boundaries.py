from __future__ import annotations

import ast
from pathlib import Path


PROTOCOL_MODULE = Path(
    ".claude/hooks/team_result_dependency_protocols.py"
)


LOWER_LEVEL_DOMAIN_MODULES = (
    Path(
        ".claude/hooks/merchant_confirmation_preferences.py"
    ),
    Path(
        ".claude/hooks/merchant_completeness_gate.py"
    ),
    Path(
        ".claude/hooks/merchant_runtime_handoff_gate.py"
    ),
    Path(
        ".claude/hooks/merchant_result_contract.py"
    ),
    Path(
        ".claude/hooks/merchant_tool_result_contract.py"
    ),
    Path(
        ".claude/hooks/team_result_contract.py"
    ),
    Path(
        ".claude/hooks/team_result_context.py"
    ),
    Path(
        ".claude/hooks/team_result_payload.py"
    ),
    Path(
        ".claude/hooks/team_result_ledger.py"
    ),
    Path(
        ".claude/hooks/resolution_staging.py"
    ),
    Path(
        ".claude/hooks/merchant_staging.py"
    ),
    Path(
        ".claude/hooks/resolution_cli_invocation.py"
    ),
)


ALLOWED_RUNTIME_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "contextlib",
    "typing",
}


def _tree(
    path: Path,
) -> ast.Module:

    return ast.parse(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def _import_root(
    module: str | None,
) -> str:

    if not module:
        return ""

    return (
        module
        .lstrip(".")
        .split(".", 1)[0]
    )


def _is_type_checking_test(
    node: ast.expr,
) -> bool:

    if (
        isinstance(
            node,
            ast.Name,
        )
        and node.id
        == "TYPE_CHECKING"
    ):
        return True

    if (
        isinstance(
            node,
            ast.Attribute,
        )
        and node.attr
        == "TYPE_CHECKING"
    ):
        return True

    return False


def _walk_runtime_statements(
    statements: list[ast.stmt],
):
    for node in statements:

        if (
            isinstance(
                node,
                ast.If,
            )
            and _is_type_checking_test(
                node.test
            )
        ):
            # Type-only branch is intentionally
            # excluded from runtime dependency scan.
            for child in _walk_runtime_statements(
                node.orelse
            ):
                yield child

            continue

        yield node

        nested_blocks = []

        if isinstance(
            node,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.With,
                ast.AsyncWith,
                ast.Try,
            ),
        ):
            nested_blocks.append(
                getattr(
                    node,
                    "body",
                    [],
                )
            )

            nested_blocks.append(
                getattr(
                    node,
                    "orelse",
                    [],
                )
            )

            nested_blocks.append(
                getattr(
                    node,
                    "finalbody",
                    [],
                )
            )

            if isinstance(
                node,
                ast.Try,
            ):
                for handler in node.handlers:
                    nested_blocks.append(
                        handler.body
                    )

        for block in nested_blocks:
            for child in _walk_runtime_statements(
                block
            ):
                yield child


def _imports_in_statements(
    statements,
):
    imports = []

    for node in statements:

        if isinstance(
            node,
            ast.Import,
        ):

            for alias in node.names:
                imports.append(
                    alias.name
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):

            module = node.module or ""

            if node.level:
                module = (
                    "." * node.level
                    + module
                )

            imports.append(
                module
            )

    return imports


def test_protocol_module_runtime_imports_are_infrastructure_only():
    tree = _tree(
        PROTOCOL_MODULE
    )

    runtime_nodes = list(
        _walk_runtime_statements(
            tree.body
        )
    )

    imports = (
        _imports_in_statements(
            runtime_nodes
        )
    )

    violations = []

    for module in imports:

        root = _import_root(
            module
        )

        if root not in (
            ALLOWED_RUNTIME_IMPORT_ROOTS
        ):
            violations.append(
                module
            )

    assert violations == [], (
        "Protocol layer gained runtime dependency "
        "on implementation/domain modules: "
        f"{violations}"
    )


def test_protocol_domain_type_imports_are_guarded_by_type_checking():
    tree = _tree(
        PROTOCOL_MODULE
    )

    type_only_imports = []

    for node in tree.body:

        if (
            not isinstance(
                node,
                ast.If,
            )
            or not _is_type_checking_test(
                node.test
            )
        ):
            continue

        type_only_imports.extend(
            _imports_in_statements(
                ast.walk(node)
            )
        )

    assert type_only_imports, (
        "Expected domain type imports under "
        "TYPE_CHECKING"
    )


def test_lower_level_domain_modules_do_not_import_protocol_layer():
    violations = []

    for path in (
        LOWER_LEVEL_DOMAIN_MODULES
    ):

        if not path.exists():
            continue

        tree = _tree(
            path
        )

        for node in ast.walk(tree):

            if isinstance(
                node,
                ast.Import,
            ):

                for alias in node.names:

                    if (
                        "team_result_dependency_protocols"
                        in alias.name
                    ):
                        violations.append(
                            (
                                path.name,
                                alias.name,
                            )
                        )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):

                module = (
                    node.module
                    or ""
                )

                if (
                    "team_result_dependency_protocols"
                    in module
                ):
                    violations.append(
                        (
                            path.name,
                            module,
                        )
                    )

    assert violations == [], (
        "Lower-level domain modules must not "
        "depend on orchestration Protocol layer: "
        f"{violations}"
    )


def test_protocol_module_does_not_import_orchestration_consumers():
    tree = _tree(
        PROTOCOL_MODULE
    )

    forbidden = {
        "post_tool_orchestrator",
        "merchant_runtime_orchestration",
        "teammate_idle_orchestrator",
        "merchant_resolution_tool_contract",
        "team_result_dispatcher",
        "team_result_hook",
    }

    violations = []

    for node in ast.walk(tree):

        if isinstance(
            node,
            ast.Import,
        ):

            modules = [
                alias.name
                for alias in node.names
            ]

        elif isinstance(
            node,
            ast.ImportFrom,
        ):

            modules = [
                node.module or ""
            ]

        else:
            continue

        for module in modules:

            tail = (
                module
                .lstrip(".")
                .split(".")[-1]
            )

            if tail in forbidden:
                violations.append(
                    tail
                )

    assert violations == [], (
        "Protocol module must not import "
        "its orchestration consumers: "
        f"{sorted(violations)}"
    )
