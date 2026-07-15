import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import fs from "node:fs/promises";
import os from "node:os";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

import {
  validatePipelineWorktreeRecord,
  getPipelineStatus,
  getPipelineDiff,
  cleanupPipelineWorktree
} from "./git-utils.js";

const execFileAsync = promisify(execFile);

async function git(workingDirectory, ...argumentsList) {
  const { stdout } = await execFileAsync(
    "git",
    argumentsList,
    { cwd: workingDirectory, encoding: "utf8" }
  );

  return stdout.trim();
}

function createWorkflow(overrides = {}) {
  const repositoryRoot = path.resolve("example-repository");
  const id = "workflow-2026-07-15-abc123";

  return {
    id,
    repositoryRoot,
    worktreePath: path.join(
      path.dirname(repositoryRoot),
      `${path.basename(repositoryRoot)}-worktrees`,
      id
    ),
    branchName: `agent/${id}`,
    baseCommit: "0123456789abcdef",
    ...overrides
  };
}

test("accepts the expected pipeline worktree record", () => {
  assert.doesNotThrow(() =>
    validatePipelineWorktreeRecord(createWorkflow())
  );
});

test("rejects a worktree outside the workflow directory", () => {
  assert.throws(
    () => validatePipelineWorktreeRecord(
      createWorkflow({
        worktreePath: path.resolve("unrelated-worktree")
      })
    ),
    /Unsafe worktree path/
  );
});

test("rejects a branch that does not belong to the workflow", () => {
  assert.throws(
    () => validatePipelineWorktreeRecord(
      createWorkflow({ branchName: "main" })
    ),
    /Unsafe branch/
  );
});

test("rejects incomplete worktree metadata", () => {
  assert.throws(
    () => validatePipelineWorktreeRecord(
      createWorkflow({ baseCommit: null })
    ),
    /does not record baseCommit/
  );
});

test("inspects and safely cleans up a real pipeline worktree", async () => {
  const temporaryRoot = await fs.mkdtemp(
    path.join(os.tmpdir(), "agent-worktree-test-")
  );

  const repositoryRoot = path.join(temporaryRoot, "project");
  const worktreesRoot = path.join(temporaryRoot, "project-worktrees");
  const id = "workflow-integration-abc123";
  const worktreePath = path.join(worktreesRoot, id);
  const branchName = `agent/${id}`;

  try {
    await fs.mkdir(repositoryRoot);
    await git(repositoryRoot, "init", "-b", "main");
    await git(repositoryRoot, "config", "user.name", "Test User");
    await git(repositoryRoot, "config", "user.email", "test@example.com");
    await fs.writeFile(
      path.join(repositoryRoot, "tracked.txt"),
      "before\n",
      "utf8"
    );
    await git(repositoryRoot, "add", "tracked.txt");
    await git(repositoryRoot, "commit", "-m", "initial");

    const baseCommit = await git(repositoryRoot, "rev-parse", "HEAD");
    await fs.mkdir(worktreesRoot);
    await git(
      repositoryRoot,
      "worktree",
      "add",
      "-b",
      branchName,
      worktreePath,
      baseCommit
    );

    const workflow = {
      id,
      repositoryRoot,
      worktreePath,
      branchName,
      baseCommit
    };

    let status = await getPipelineStatus(workflow);
    assert.equal(status.isClean, true);
    assert.equal(status.commitsAhead, 0);

    await fs.writeFile(
      path.join(worktreePath, "tracked.txt"),
      "after\n",
      "utf8"
    );
    await fs.writeFile(
      path.join(worktreePath, "new.txt"),
      "new\n",
      "utf8"
    );

    status = await getPipelineStatus(workflow);
    assert.equal(status.isClean, false);

    const result = await getPipelineDiff(workflow);
    assert.match(result.diff, /before/);
    assert.match(result.diff, /after/);
    assert.deepEqual(result.untrackedFiles, ["new.txt"]);

    await assert.rejects(
      cleanupPipelineWorktree(workflow),
      /uncommitted changes/
    );

    await cleanupPipelineWorktree(
      workflow,
      { discard: true }
    );

    await assert.rejects(fs.access(worktreePath));
    const branches = await git(repositoryRoot, "branch", "--list", branchName);
    assert.equal(branches, "");
  } finally {
    await fs.rm(temporaryRoot, {
      recursive: true,
      force: true
    });
  }
});