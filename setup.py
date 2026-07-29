"""Setup configuration for Coding Agent Workspace."""

from setuptools import setup, find_packages

setup(
    name="coding-agent-workspace",
    version="0.2.0",
    description="Claude Code agent orchestration system for code analysis and automation",
    author="Nguyen Le Dang Nguyen",
    author_email="nguyen.nguyen30@momo.vn",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "coding-agent-workspace=workspace_cli.cli:main",
        ],
    },
    include_package_data=True,
)
