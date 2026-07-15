import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

function runGit(
  argumentsList,
  workingDirectory = process.cwd()
) {
  return new Promise((resolve, reject) => {
    execFile(
      "git",
      argumentsList,
      {
        cwd: workingDirectory,
        encoding: "utf8"
      },
      (error, stdout, stderr) => {
        if (error) {
          reject(
            new Error(
              stderr.trim() ||
              error.message
            )
          );

          return;
        }

        resolve(stdout.trim());
      }
    );
  });
}

function samePath(first, second) {
  const normalize = (value) => {
    const resolved = path.resolve(value);

    return process.platform === "win32"
      ? resolved.toLowerCase()
      : resolved;
  };

  return normalize(first) === normalize(second);
}

function resolveGitPath(workingDirectory, gitPath) {
  return path.resolve(workingDirectory, gitPath);
}

export async function getGitStatus(
  workingDirectory = process.cwd()
) {
  try {
    const branch = await runGit(
      [
        "branch",
        "--show-current"
      ],
      workingDirectory
    );

    const changes = await runGit(
      [
        "status",
        "--porcelain"
      ],
      workingDirectory
    );

    return {
      isRepository: true,
      branch:
        branch || "(detached HEAD)",
      isClean: changes.length === 0,
      changes: changes
        ? changes.split("\n")
        : []
    };
  } catch {
    return {
      isRepository: false,
      branch: null,
      isClean: false,
      changes: []
    };
  }
}

export async function requireCleanRepository(
  workingDirectory = process.cwd()
) {
  const status = await getGitStatus(
    workingDirectory
  );

  if (!status.isRepository) {
    throw new Error(
      "Write agents require a Git repository"
    );
  }

  if (!status.isClean) {
    throw new Error(
      [
        "Write agents require a clean working tree.",
        "Commit or stash your current changes first.",
        "",
        ...status.changes
      ].join("\n")
    );
  }

  return status;
}

export async function createPipelineWorktree(
  workflowId
) {
  validateWorkflowId(workflowId);

  const repositoryRoot = await runGit([
    "rev-parse",
    "--show-toplevel"
  ]);

  const baseCommit = await runGit([
    "rev-parse",
    "HEAD"
  ]);

  const repositoryName =
    path.basename(repositoryRoot);

  const worktreesRoot = path.join(
    path.dirname(repositoryRoot),
    `${repositoryName}-worktrees`
  );

  const worktreePath = path.join(
    worktreesRoot,
    workflowId
  );

  const branchName =
    `agent/${workflowId}`;

  await fs.mkdir(worktreesRoot, {
    recursive: true
  });

  await runGit([
    "worktree",
    "add",
    "-b",
    branchName,
    worktreePath,
    baseCommit
  ]);

  return {
    repositoryRoot,
    worktreePath,
    branchName,
    baseCommit
  };
}

export function validatePipelineWorktreeRecord(
  workflow
) {
  validateWorkflowId(workflow?.id);

  const requiredFields = [
    "repositoryRoot",
    "worktreePath",
    "branchName",
    "baseCommit"
  ];

  for (const field of requiredFields) {
    if (!workflow[field]) {
      throw new Error(
        `Workflow ${workflow.id} does not record ${field}`
      );
    }
  }

  const expectedRoot = path.join(
    path.dirname(workflow.repositoryRoot),
    `${path.basename(workflow.repositoryRoot)}-worktrees`
  );

  const expectedPath = path.join(
    expectedRoot,
    workflow.id
  );

  if (!samePath(workflow.worktreePath, expectedPath)) {
    throw new Error(
      `Unsafe worktree path recorded for workflow ${workflow.id}`
    );
  }

  const expectedBranch = `agent/${workflow.id}`;

  if (workflow.branchName !== expectedBranch) {
    throw new Error(
      `Unsafe branch recorded for workflow ${workflow.id}`
    );
  }
}

export async function getPipelineStatus(workflow) {
  validatePipelineWorktreeRecord(workflow);

  const repositoryRoot = await runGit(
    ["rev-parse", "--show-toplevel"],
    workflow.repositoryRoot
  );

  if (!samePath(repositoryRoot, workflow.repositoryRoot)) {
    throw new Error(
      "Recorded repository root does not match the Git repository"
    );
  }

  const repositoryCommonDirectory =
    resolveGitPath(
      workflow.repositoryRoot,
      await runGit(
        ["rev-parse", "--git-common-dir"],
        workflow.repositoryRoot
      )
    );

  const worktreeRoot = await runGit(
    ["rev-parse", "--show-toplevel"],
    workflow.worktreePath
  );

  if (!samePath(worktreeRoot, workflow.worktreePath)) {
    throw new Error(
      "Recorded worktree path does not match the Git worktree"
    );
  }

  const worktreeCommonDirectory =
    resolveGitPath(
      workflow.worktreePath,
      await runGit(
        ["rev-parse", "--git-common-dir"],
        workflow.worktreePath
      )
    );

  if (!samePath(
    repositoryCommonDirectory,
    worktreeCommonDirectory
  )) {
    throw new Error(
      "Recorded worktree does not belong to the recorded repository"
    );
  }

  const branch = await runGit(
    ["branch", "--show-current"],
    workflow.worktreePath
  );

  if (branch !== workflow.branchName) {
    throw new Error(
      `Worktree branch mismatch: expected ${workflow.branchName}, found ${branch || "detached HEAD"}`
    );
  }

  const status = await getGitStatus(
    workflow.worktreePath
  );

  const headCommit = await runGit(
    ["rev-parse", "HEAD"],
    workflow.worktreePath
  );

  return {
    ...status,
    repositoryRoot,
    worktreePath: worktreeRoot,
    headCommit,
    baseCommit: workflow.baseCommit,
    commitsAhead: Number(
      await runGit(
        ["rev-list", "--count", `${workflow.baseCommit}..HEAD`],
        workflow.worktreePath
      )
    )
  };
}

export async function getPipelineDiff(workflow) {
  await getPipelineStatus(workflow);

  const diff = await runGit(
    ["diff", "--no-ext-diff", workflow.baseCommit],
    workflow.worktreePath
  );

  const untracked = await runGit(
    ["ls-files", "--others", "--exclude-standard"],
    workflow.worktreePath
  );

  return {
    diff,
    untrackedFiles: untracked
      ? untracked.split("\n")
      : []
  };
}

export async function cleanupPipelineWorktree(
  workflow,
  { discard = false } = {}
) {
  const status = await getPipelineStatus(workflow);

  if (!status.isClean && !discard) {
    throw new Error(
      "Pipeline worktree has uncommitted changes. Re-run with --discard to remove them explicitly."
    );
  }

  const removeArguments = [
    "worktree",
    "remove"
  ];

  if (discard) {
    removeArguments.push("--force");
  }

  removeArguments.push(workflow.worktreePath);

  await runGit(
    removeArguments,
    workflow.repositoryRoot
  );

  await runGit(
    ["branch", discard ? "-D" : "-d", workflow.branchName],
    workflow.repositoryRoot
  );

  return {
    worktreePath: workflow.worktreePath,
    branchName: workflow.branchName
  };
}

function validateWorkflowId(workflowId) {
  if (
    !workflowId ||
    !/^workflow-[a-zA-Z0-9-]+$/.test(
      workflowId
    )
  ) {
    throw new Error(
      `Invalid workflow ID: ${workflowId}`
    );
  }
}