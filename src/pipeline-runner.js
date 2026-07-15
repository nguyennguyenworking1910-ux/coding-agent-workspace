import {
  executeAgentRun
} from "./agent-runner.js";

import {
  requireCleanRepository,
  createPipelineWorktree,
  cleanupPipelineWorktree
} from "./git-utils.js";

import {
  createWorkflow,
  setWorkflowWorktree,
  addWorkflowStage,
  completeWorkflow,
  failWorkflow
} from "./workflow-store.js";

export async function executePipeline(task) {
  if (!task?.trim()) {
    throw new Error(
      "Pipeline task is required"
    );
  }

  const gitStatus =
    await requireCleanRepository();

  const {
    workflow,
    workflowDirectory
  } = await createWorkflow(task);

  const results = [];

  let currentStage =
    "worktree-setup";

  let worktree = null;

  try {
    worktree =
      await createPipelineWorktree(
        workflow.id
      );

    try {
      await setWorkflowWorktree(
        workflow,
        workflowDirectory,
        worktree
      );
    } catch (metadataError) {
      try {
        await cleanupPipelineWorktree(
          workflow,
          { discard: true }
        );

        worktree = null;
      } catch (cleanupError) {
        metadataError.message = [
          metadataError.message,
          `Recovery cleanup failed: ${cleanupError.message}`,
          `Worktree may remain at: ${worktree.worktreePath}`
        ].join("\n");
      }

      throw metadataError;
    }

    console.log("Coding Agent Pipeline");
    console.log("---------------------");

    console.log(
      `Workflow ID: ${workflow.id}`
    );

    console.log(
      `Base branch: ${gitStatus.branch}`
    );

    console.log(
      `Pipeline branch: ${worktree.branchName}`
    );

    console.log(
      `Base commit: ${worktree.baseCommit}`
    );

    console.log(
      `Worktree: ${worktree.worktreePath}`
    );

    console.log(`Task: ${task}`);

    console.log(
      "Isolated worktree created successfully."
    );

    currentStage = "diagnostician";

    console.log(
      "\n[Stage 1/4] Diagnostician"
    );

    const diagnosis =
      await executeAgentRun(
        "diagnostician",
        task,
        null,
        {
          workflowId: workflow.id,
          workingDirectory:
            worktree.worktreePath
        }
      );

    results.push(diagnosis.run);

    await addWorkflowStage(
      workflow,
      workflowDirectory,
      diagnosis.run
    );

    currentStage = "bug-fixer";

    console.log(
      "\n[Stage 2/4] Bug-fixer"
    );

    const fix =
      await executeAgentRun(
        "bug-fixer",
        createBugFixerTask(task),
        diagnosis.run.id,
        {
          workflowId: workflow.id,
          workingDirectory:
            worktree.worktreePath,
          skipGitSafety: true
        }
      );

    results.push(fix.run);

    await addWorkflowStage(
      workflow,
      workflowDirectory,
      fix.run
    );

    currentStage = "test-agent";

    console.log(
      "\n[Stage 3/4] Test-agent"
    );

    const tests =
      await executeAgentRun(
        "test-agent",
        createTestTask(task),
        fix.run.id,
        {
          workflowId: workflow.id,
          workingDirectory:
            worktree.worktreePath,
          skipGitSafety: true
        }
      );

    results.push(tests.run);

    await addWorkflowStage(
      workflow,
      workflowDirectory,
      tests.run
    );

    currentStage = "reviewer";

    console.log(
      "\n[Stage 4/4] Reviewer"
    );

    const review =
      await executeAgentRun(
        "reviewer",
        createReviewTask(task),
        tests.run.id,
        {
          workflowId: workflow.id,
          workingDirectory:
            worktree.worktreePath
        }
      );

    results.push(review.run);

    await addWorkflowStage(
      workflow,
      workflowDirectory,
      review.run
    );

    await completeWorkflow(
      workflow,
      workflowDirectory
    );

    printPipelineSummary(
      workflow,
      results
    );

    return {
      workflow,
      workflowDirectory,
      worktree,
      runs: results
    };
  } catch (error) {
    if (error.runId) {
      await addWorkflowStage(
        workflow,
        workflowDirectory,
        {
          id: error.runId,
          agent:
            error.agentName ??
            currentStage,
          status: "failed"
        }
      );
    }

    await failWorkflow(
      workflow,
      workflowDirectory,
      error
    );

    console.error(
      `\nPipeline failed at stage: ${currentStage}`
    );

    console.error(
      `Workflow ID: ${workflow.id}`
    );

    if (worktree?.worktreePath) {
      console.error(
        `Worktree preserved at: ${worktree.worktreePath}`
      );
    }

    throw error;
  }
}

function createBugFixerTask(
  originalTask
) {
  return `
Implement a focused fix for the following task:

${originalTask}

Use the diagnostician report as supporting context.

Requirements:

- Independently verify the diagnosis before modifying files.
- Make only focused changes needed to solve the problem.
- Preserve the existing architecture and conventions.
- Do not install packages.
- Do not create commits.
- Report every changed file.
`.trim();
}

function createTestTask(
  originalTask
) {
  return `
Create or update regression tests for the following task:

${originalTask}

Inspect the current implementation and the bug-fixer report.

Requirements:

- Independently verify the implemented behavior.
- Add tests that reproduce the original problem.
- Do not weaken or remove existing assertions.
- Run only approved test commands.
- Report the exact commands executed.
- Report the real pass or fail results.
- Do not install packages.
- Do not create commits.
`.trim();
}

function createReviewTask(
  originalTask
) {
  return `
Review the final implementation for the following task:

${originalTask}

Inspect the current repository state, implementation changes,
and available tests.

Review for:

- Correctness.
- Regression risk.
- Error handling.
- Edge cases.
- Security issues.
- Missing test coverage.
- Unnecessary scope expansion.
- Maintainability.

Do not modify files.

Clearly separate blocking findings from non-blocking
recommendations.
`.trim();
}

function printPipelineSummary(
  workflow,
  runs
) {
  console.log(
    "\nPipeline completed successfully.\n"
  );

  console.log(
    `Workflow ID: ${workflow.id}`
  );

  console.log(
    `Pipeline branch: ${workflow.branchName}`
  );

  console.log(
    `Base commit: ${workflow.baseCommit}`
  );

  console.log(
    `Worktree: ${workflow.worktreePath}`
  );

  console.table(
    runs.map((run) => ({
      agent: run.agent,
      status: run.status,
      runId: run.id,
      workflow:
        run.workflowId?.slice(-6) ??
        "-",
      parent:
        run.parentRunId?.slice(-6) ??
        "-",
      context:
        run.contextRunId?.slice(-6) ??
        "-"
    }))
  );

  console.log(
    "\nChanges are isolated from the main working tree."
  );

  console.log(
    "Inspect the pipeline worktree before committing or merging."
  );
}