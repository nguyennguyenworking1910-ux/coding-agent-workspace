import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"


def load_claude_package() -> None:
    """Expose `.claude` through its importable package name."""
    if "claude" in sys.modules:
        return

    package = types.ModuleType("claude")
    package.__path__ = [str(CLAUDE_DIR)]
    package.__package__ = "claude"
    sys.modules["claude"] = package


load_claude_package()

rag_module = importlib.import_module(
    "claude.agents.tools.rag.search"
)
rag_package = importlib.import_module(
    "claude.agents.tools.rag"
)


def load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "rag_search_cli",
        CLAUDE_DIR / "rag_search.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeRagClient:
    def __init__(self):
        self.ready_calls = 0
        self.search_calls = []

    def ready(self):
        self.ready_calls += 1
        return {"status": "ok"}

    def search(self, query, **kwargs):
        self.search_calls.append(
            {
                "query": query,
                **kwargs,
            }
        )
        return {
            "results": [],
            "result_count": 0,
            "embedding_model": "BAAI/bge-m3",
            "elapsed_ms": 100,
        }


def test_tool_registry_exposes_ready_and_search():
    assert set(rag_package.RAG_TOOLS) == {
        "ready",
        "search",
    }


def test_ready_delegates_to_client(monkeypatch):
    client = FakeRagClient()
    monkeypatch.setattr(rag_module, "_rag_client", client)

    response = rag_module.ready()

    assert response == {"status": "ok"}
    assert client.ready_calls == 1


def test_search_delegates_all_arguments(monkeypatch):
    client = FakeRagClient()
    monkeypatch.setattr(rag_module, "_rag_client", client)

    response = rag_module.search(
        "intent gate",
        top_k=3,
        candidate_k=20,
        source_types=["project_document"],
        source_keys=["workspace:CLAUDE.md"],
    )

    assert response["result_count"] == 0
    assert client.search_calls == [
        {
            "query": "intent gate",
            "top_k": 3,
            "candidate_k": 20,
            "source_types": ["project_document"],
            "source_keys": ["workspace:CLAUDE.md"],
        }
    ]


def test_cli_search_emits_json(monkeypatch, capsys):
    cli = load_cli_module()
    captured_arguments = {}

    def fake_search(query, **kwargs):
        captured_arguments.update(
            {
                "query": query,
                **kwargs,
            }
        )
        return {
            "results": [],
            "result_count": 0,
            "embedding_model": "BAAI/bge-m3",
            "elapsed_ms": 80,
        }

    monkeypatch.setattr(cli, "tool_search", fake_search)

    exit_code = cli.main(
        [
            "intent gate",
            "--top-k",
            "3",
            "--candidate-k",
            "20",
            "--source-type",
            "project_document",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["result_count"] == 0
    assert captured_arguments == {
        "query": "intent gate",
        "top_k": 3,
        "candidate_k": 20,
        "source_types": ["project_document"],
        "source_keys": [],
    }


def test_cli_ready_emits_json(monkeypatch, capsys):
    cli = load_cli_module()
    monkeypatch.setattr(
        cli,
        "tool_ready",
        lambda: {"status": "ok"},
    )

    exit_code = cli.main(["--ready"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == {"status": "ok"}