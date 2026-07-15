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