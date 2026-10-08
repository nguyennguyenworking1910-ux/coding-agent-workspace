from __future__ import annotations

import ast
from pathlib import Path


HOOK = Path(
    ".claude/hooks/team_result_hook.py"
)


DEPENDENCY_MODULES = (
    Path(
        ".claude/hooks/post_tool_orchestrator.py"
    ),
    Path(
        ".claude/hooks/merchant_runtime_orchestration.py"
    ),
    Path(
        ".claude/hooks/teammate_idle_orchestrator.py"
    ),
    Path(
        ".claude/hooks/merchant_resolution_tool_contract.py"
    ),
    Path(
        ".claude/hooks/team_result_dispatcher.py"
    ),
)


EXPECTED_CONTRACTS = {
    Path(
        ".claude/hooks/post_tool_orchestrator.py"
    ): "PostToolDependencies",

    Path(
        ".claude/hooks/merchant_runtime_orchestration.py"
    ): "MerchantRuntimeDependencies",

    Path(
        ".claude/hooks/teammate_idle_orchestrator.py"
    ): "TeammateIdleDependencies",

    Path(
        ".claude/hooks/merchant_resolution_tool_contract.py"
    ): "ResidualMerchantDependencies",

    Path(
        ".claude/hooks/team_result_dispatcher.py"
    ): "DispatcherDependencies",
}


def _tree(
    path: Path,
) -> ast.Module:

    return ast.parse(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def test_team_result_hook_has_no_dependency_view_classes():
    tree = _tree(
        HOOK
    )

    dependency_views = [
        node.name
        for node in tree.body
        if (
            isinstance(
                node,
                ast.ClassDef,
            )
            and node.name.endswith(
                "DependencyView"
            )
        )
    ]

    assert dependency_views == []


def test_team_result_hook_has_no_dynamic_globals_dependency_lookup():
    text = HOOK.read_text(
        encoding="utf-8-sig"
    )

    assert "globals()[" not in text


def test_each_orchestration_module_has_exactly_one_dependency_contract():
    for (
        path,
        expected_name,
    ) in EXPECTED_CONTRACTS.items():

        tree = _tree(
            path
        )

        contracts = [
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
                and node.name.endswith(
                    "Dependencies"
                )
            )
        ]

        assert (
            len(contracts) == 1
        ), (
            f"{path} must define exactly one "
            f"dependency contract"
        )

        assert (
            contracts[0].name
            == expected_name
        )


def test_dependency_contracts_are_frozen_dataclasses():
    for path in DEPENDENCY_MODULES:

        tree = _tree(
            path
        )

        contract = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
                and node.name.endswith(
                    "Dependencies"
                )
            )
        )

        dataclass_calls = [
            decorator
            for decorator
            in contract.decorator_list
            if (
                isinstance(
                    decorator,
                    ast.Call,
                )
                and isinstance(
                    decorator.func,
                    ast.Name,
                )
                and decorator.func.id
                == "dataclass"
            )
        ]

        assert (
            len(dataclass_calls) == 1
        ), (
            f"{path}:{contract.name} "
            f"must be a dataclass"
        )

        frozen_values = []

        for keyword in (
            dataclass_calls[0].keywords
        ):

            if keyword.arg != "frozen":
                continue

            frozen_values.append(
                keyword.value
            )

        assert (
            len(frozen_values) == 1
        ), (
            f"{path}:{contract.name} "
            f"must explicitly set frozen=True"
        )

        frozen = frozen_values[0]

        assert (
            isinstance(
                frozen,
                ast.Constant,
            )
            and frozen.value is True
        ), (
            f"{path}:{contract.name} "
            f"must use @dataclass(frozen=True)"
        )


def test_dependency_contracts_have_annotated_fields_only():
    for path in DEPENDENCY_MODULES:

        tree = _tree(
            path
        )

        contract = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
                and node.name.endswith(
                    "Dependencies"
                )
            )
        )

        assignments = [
            node
            for node in contract.body
            if isinstance(
                node,
                ast.Assign,
            )
        ]

        assert assignments == [], (
            f"{path}:{contract.name} "
            f"must use explicit annotated fields"
        )


def test_hook_dependency_factories_are_call_time_functions():
    tree = _tree(
        HOOK
    )

    expected_factories = {
        "_post_tool_dependencies",
        "_merchant_runtime_dependencies",
        "_teammate_idle_dependencies",
        "_residual_merchant_dependencies",
        "_dispatcher_dependencies",
    }

    functions = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }

    missing = (
        expected_factories
        - functions
    )

    assert missing == set(), (
        f"Missing call-time dependency factories: "
        f"{sorted(missing)}"
    )


def test_hook_has_no_dependency_singleton_assignments():
    tree = _tree(
        HOOK
    )

    forbidden = []

    for node in tree.body:

        if not isinstance(
            node,
            ast.Assign,
        ):
            continue

        for target in node.targets:

            if (
                isinstance(
                    target,
                    ast.Name,
                )
                and target.id.endswith(
                    "_DEPENDENCIES"
                )
            ):

                forbidden.append(
                    target.id
                )

    assert forbidden == [], (
        "Dependency contracts must be constructed "
        "at call time, not stored in module-level "
        f"singletons: {forbidden}"
    )
