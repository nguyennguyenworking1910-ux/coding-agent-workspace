"""
Test that .claude/settings.json has correct Read deny rules for environment files.

This test verifies:
- .env.example is NOT blocked (it's safe to read as a template)
- root .env IS blocked (contains secrets)
- All environment variants ARE blocked: .env.local, .env.development, .env.test, .env.staging, .env.production, .env.*.local
- Legacy files ARE blocked: .env.rag, .claude/clients/.env, .claude/agents/team/.env
- All credential/token/service-account denies remain present
"""

import json
import re
from pathlib import Path


def load_settings():
    """Load .claude/settings.json."""
    settings_path = Path(".claude/settings.json")
    with open(settings_path) as f:
        return json.load(f)


def parse_deny_rule(rule):
    """
    Parse a deny rule like 'Read(./.env)' or 'Read(./.env.*)'
    Returns (tool_name, path_pattern)
    """
    match = re.match(r'(\w+)\((.*)\)', rule)
    if match:
        return match.group(1), match.group(2)
    return None, None


def extract_read_patterns(deny_rules):
    """Extract all Read(...) patterns from deny rules."""
    patterns = []
    for rule in deny_rules:
        tool_name, path_pattern = parse_deny_rule(rule)
        if tool_name == 'Read':
            # Remove quotes and leading ./
            pattern = path_pattern.strip('"').replace('\\', '/')
            if pattern.startswith('./'):
                pattern = pattern[2:]
            patterns.append((pattern, rule))
    return patterns


def is_path_blocked(path, deny_rules):
    """
    Check if a path is blocked by any deny rule.
    Uses simple glob matching with fnmatch.

    Args:
        path: The file path to check (e.g., '.env', '.env.example')
        deny_rules: List of deny rules (e.g., ['Read(./.env)', 'Read(./.env.local)'])

    Returns:
        tuple: (is_blocked, matching_rule)
    """
    import fnmatch

    # Normalize path - remove ./ prefix (use removeprefix if available, else manual)
    test_path = path.replace('\\', '/')
    if test_path.startswith('./'):
        test_path = test_path[2:]

    patterns = extract_read_patterns(deny_rules)
    for pattern, rule in patterns:
        if fnmatch.fnmatch(test_path, pattern):
            return True, rule

    return False, None


def test_env_example_not_blocked():
    """Test that .env.example is NOT blocked."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    is_blocked, rule = is_path_blocked('./.env.example', deny_rules)
    assert not is_blocked, f".env.example should NOT be blocked, but matched rule: {rule}"


def test_root_env_blocked():
    """Test that root .env IS blocked."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    is_blocked, rule = is_path_blocked('./.env', deny_rules)
    assert is_blocked, ".env should be blocked"


def test_env_variants_blocked():
    """Test that all environment variants are blocked."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    variants = [
        './.env.local',
        './.env.development',
        './.env.test',
        './.env.staging',
        './.env.production',
        './.env.local.local',  # .env.*.local pattern
    ]

    for variant in variants:
        is_blocked, rule = is_path_blocked(variant, deny_rules)
        assert is_blocked, f"{variant} should be blocked but wasn't. Check deny rules."


def test_legacy_files_blocked():
    """Test that legacy environment files are blocked."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    legacy_files = [
        './.env.rag',
        './.claude/clients/.env',
        './.claude/agents/team/.env',
    ]

    for legacy_file in legacy_files:
        is_blocked, rule = is_path_blocked(legacy_file, deny_rules)
        assert is_blocked, f"{legacy_file} should be blocked but wasn't. Check deny rules."


def test_credential_denies_present():
    """Test that all credential/token/service-account denies remain present."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    required_denies = [
        'Read(./credentials.json)',
        'Read(./token.json)',
        'Read(./service_account.json)',
    ]

    for required_deny in required_denies:
        assert required_deny in deny_rules, f"Missing required deny rule: {required_deny}"


def test_no_overly_broad_glob():
    """Test that there is no overly broad Read(./.env.*) rule."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    # This overly broad rule blocks .env.example too
    overly_broad = 'Read(./.env.*)'

    assert overly_broad not in deny_rules, (
        f"Found overly broad rule '{overly_broad}' that blocks .env.example. "
        "Use specific deny rules instead (e.g., Read(./.env.local), Read(./.env.development))"
    )


def test_all_deny_rules_valid():
    """Test that all deny rules have valid format."""
    settings = load_settings()
    deny_rules = settings['permissions']['deny']

    pattern = re.compile(r'^\w+\(.+\)$')
    for rule in deny_rules:
        assert pattern.match(rule), f"Invalid deny rule format: {rule}"


if __name__ == '__main__':
    # Run all tests
    print("Running settings permission tests...")

    test_env_example_not_blocked()
    print("[PASS] .env.example is not blocked")

    test_root_env_blocked()
    print("[PASS] root .env is blocked")

    test_env_variants_blocked()
    print("[PASS] all environment variants are blocked")

    test_legacy_files_blocked()
    print("[PASS] legacy files are blocked")

    test_credential_denies_present()
    print("[PASS] all credential/token/service-account denies are present")

    test_no_overly_broad_glob()
    print("[PASS] no overly broad Read(./.env.*) rule")

    test_all_deny_rules_valid()
    print("[PASS] all deny rules have valid format")

    print("\nAll tests passed!")
