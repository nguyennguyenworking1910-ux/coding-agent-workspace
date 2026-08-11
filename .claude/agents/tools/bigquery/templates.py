"""Discovery, parsing, and validation of `.sql` query templates.

Adding a query to this system means dropping a `.sql` file into the templates
directory (`config.BIGQUERY_TEMPLATE_DIR`) - nothing here needs editing. The file
name minus `.sql` is the template name, and every `@placeholder` in the SQL becomes
a required parameter.

A template may open with an optional `--` comment header describing itself:

    -- description: Daily row counts for one date range.
    -- params:
    --   start_date: DATE - first day, inclusive
    --   end_date: DATE - last day, inclusive

The header is a convenience, not a contract: a bare `.sql` file with no comments at
all works, and its parameters are still reported from the SQL itself.

Note: this module shadows the sibling `templates/` data directory as far as Python
imports are concerned (a module wins over a directory with no `__init__.py`), which
is intentional - the directory holds SQL, never Python.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ....clients import config

TEMPLATE_SUFFIX = ".sql"

# Template names map to file names, so they are restricted to characters that
# cannot escape the templates directory or mean something to a shell.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")

# BigQuery named parameter: @ followed by an identifier. `@@name` is a system
# variable, not a parameter, and is excluded by the negative lookbehind.
_PARAM_REF = re.compile(r"(?<!@)@([A-Za-z_][A-Za-z0-9_]*)")

_PARAM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class TemplateError(RuntimeError):
    """A template could not be found, read, or satisfied by the given parameters."""


def template_dir() -> Path:
    """The directory `.sql` templates are read from."""
    return Path(config.BIGQUERY_TEMPLATE_DIR)


def _strip_comments_and_literals(sql: str) -> str:
    """Blank out comments and string literals so only real SQL tokens remain.

    A deliberately tolerant scanner, not a SQL parser: it exists so that an `@word`
    inside a comment or a quoted string is not mistaken for a query parameter.
    Unterminated quotes are treated as ending at the newline rather than raising.
    """
    out: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        pair = sql[i:i + 2]

        # Line comments: -- and # both run to end of line in BigQuery.
        if pair == "--" or ch == "#":
            newline = sql.find("\n", i)
            i = n if newline == -1 else newline
            continue

        # Block comment.
        if pair == "/*":
            close = sql.find("*/", i + 2)
            i = n if close == -1 else close + 2
            continue

        # Quoted string, triple-quoted string, or backquoted identifier.
        if ch in "'\"`":
            triple = sql[i:i + 3]
            if triple in ("'''", '"""'):
                close = sql.find(triple, i + 3)
                i = n if close == -1 else close + 3
                continue
            j = i + 1
            while j < n:
                c = sql[j]
                if c == "\\" and ch != "`":
                    j += 2
                    continue
                if c == ch or c == "\n":
                    break
                j += 1
            i = j + 1
            continue

        out.append(ch)
        i += 1
    return "".join(out)


def is_valid_param_name(name: Any) -> bool:
    """True if `name` can be a BigQuery named parameter (a plain identifier)."""
    return isinstance(name, str) and bool(_PARAM_NAME.fullmatch(name))


def extract_param_names(sql: str) -> List[str]:
    """The `@param` names a query needs, in order of first appearance."""
    stripped = _strip_comments_and_literals(sql)
    names: List[str] = []
    for match in _PARAM_REF.finditer(stripped):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def _parse_header(sql: str) -> Dict[str, Any]:
    """Read the optional leading `--` comment block.

    Recognises `description:` and a `params:` block of `name: TYPE - notes` lines.
    Anything else in the header is treated as prose description. Returns empty
    values when there is no header, which is the normal case for a dropped-in file.
    """
    description: List[str] = []
    param_docs: Dict[str, str] = {}
    in_params = False
    started = False

    for raw in sql.splitlines():
        line = raw.strip()
        if not line:
            if started:
                break  # a blank line closes the header block
            continue
        if not line.startswith("--"):
            break
        started = True

        body = line.lstrip("-").strip()
        if not body:
            continue
        lowered = body.lower()

        if lowered.startswith(("params:", "parameters:")):
            in_params = True
            inline = body.split(":", 1)[1].strip()
            if inline:
                body, lowered = inline, inline.lower()
            else:
                continue

        if lowered.startswith("description:"):
            in_params = False
            description.append(body.split(":", 1)[1].strip())
            continue

        if in_params:
            entry = body.lstrip("*-").strip()
            if ":" in entry:
                name, doc = entry.split(":", 1)
                name = name.strip()
                if _PARAM_NAME.fullmatch(name):
                    param_docs[name] = doc.strip()
            continue

        description.append(body)

    return {
        "description": " ".join(part for part in description if part) or None,
        "param_docs": param_docs,
    }


def _template_path(name: str) -> Path:
    """Resolve a template name to a path inside the templates directory.

    The name is a file name, never a path: separators, `..`, and absolute paths are
    rejected, and the resolved file is confirmed to sit inside the directory.
    """
    if not isinstance(name, str) or not name.strip():
        raise TemplateError("No template name given. Run with --list to see the options.")

    candidate = name.strip()
    if candidate.lower().endswith(TEMPLATE_SUFFIX):
        candidate = candidate[: -len(TEMPLATE_SUFFIX)]

    if not _SAFE_NAME.fullmatch(candidate) or ".." in candidate:
        raise TemplateError(
            f"Invalid template name '{name}'. Use the file name without the "
            f"'{TEMPLATE_SUFFIX}' extension - letters, digits, '_', '-', and '.' only."
        )

    directory = template_dir().resolve()
    path = (directory / f"{candidate}{TEMPLATE_SUFFIX}").resolve()
    if path.parent != directory:
        raise TemplateError(
            f"Template '{name}' resolves outside {directory} and was refused."
        )
    if not path.is_file():
        available = ", ".join(list_templates()) or "(none yet)"
        raise TemplateError(
            f"Template '{candidate}' not found in {directory}.\n"
            f"Available templates: {available}\n"
            f"To add one, drop a {TEMPLATE_SUFFIX} file into that directory."
        )
    return path


def list_templates() -> List[str]:
    """The names of every `.sql` template available, sorted.

    Returns an empty list - not an error - when the directory is missing or empty.
    """
    directory = template_dir()
    if not directory.is_dir():
        return []
    return sorted(
        path.stem
        for path in directory.glob(f"*{TEMPLATE_SUFFIX}")
        if path.is_file()
    )


def get_template(name: str) -> str:
    """The raw SQL text of a template.

    Args:
        name: Template name (the file name without `.sql`)

    Returns:
        The file contents, unmodified
    """
    path = _template_path(name)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise TemplateError(f"Could not read template '{name}' at {path}: {e}")


def describe_template(name: str) -> Dict[str, Any]:
    """Describe a template: its parameters, its header description, and its SQL.

    Args:
        name: Template name (the file name without `.sql`)

    Returns:
        Dict with `name`, `path`, `description`, `params` (required `@names` in
        order), `param_docs` (types/notes from the header, may be empty), and `sql`
    """
    path = _template_path(name)
    sql = get_template(name)
    header = _parse_header(sql)
    return {
        "name": path.stem,
        "path": str(path),
        "description": header["description"],
        "params": extract_param_names(sql),
        "param_docs": header["param_docs"],
        "sql": sql,
    }


def describe_templates() -> List[Dict[str, Any]]:
    """Describe every available template, skipping the `sql` body.

    The listing an agent or the CLI shows; full SQL is one `describe_template` away.
    """
    described = []
    for name in list_templates():
        info = describe_template(name)
        info.pop("sql", None)
        described.append(info)
    return described


def validate_params(name: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Check a parameter dict against what a template actually references.

    Fails here, naming the exact parameters at fault, rather than letting BigQuery
    reject the job with a less specific message.

    Args:
        name: Template name
        params: Mapping of parameter name to Python value

    Returns:
        A plain dict copy of the parameters, in the order the template uses them
    """
    given = dict(params or {})
    required = extract_param_names(get_template(name))

    missing = [p for p in required if p not in given]
    extra = [p for p in given if p not in required]

    if missing or extra:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"not used by this template: {', '.join(extra)}")
        expected = ", ".join(required) or "(none)"
        raise TemplateError(
            f"Parameter mismatch for template '{name}' ({'; '.join(details)}).\n"
            f"This template requires: {expected}"
        )

    return {p: given[p] for p in required}
