import {
  executeAgentRun
} from "./agent-runner.js";

import {
  requireCleanRepository
} from "./git-utils.js";

export async function executePipeline(task) {
  if (!task?.trim()) {
    throw new Error(
      "Pipeline task is required"
    );
  }

  const gitStatus =
    await requireCleanRepository();

  console.log("Coding Agent Pipeline");
  console.log("---------------------");
  console.log(`Branch: ${gitStatus.branch}`);
  console.log(`Task: ${task}`);
  console.log(
    "Initial Git safety check passed."
  );

  const results = [];

  console.log(
    "\n[Stage 1/4] Diagnostician"
  );

  const diagnosis =
    await executeAgentRun(
      "diagnostician",
      task
    );

  results.push(diagnosis.run);

  console.log(
    "\n[Stage 2/4] Bug-fixer"
  );

  const fix = await executeAgentRun(
    "bug-fixer",
    createBugFixerTask(task),
    diagnosis.run.id,
    {
      skipGitSafety: true
    }
  );

  results.push(fix.run);

  console.log(
    "\n[Stage 3/4] Test-agent"
  );

  const tests = await executeAgentRun(
    "test-agent",
    createTestTask(task),
    fix.run.id,
    {
      skipGitSafety: true
    }
  );

  results.push(tests.run);

  console.log(
    "\n[Stage 4/4] Reviewer"
  );

  const review = await executeAgentRun(
    "reviewer",
    createReviewTask(task),
    tests.run.id
  );

  results.push(review.run);

  printPipelineSummary(results);

  return {
    rootRunId: diagnosis.run.id,
    runs: results
  };
}

function createBugFixerTask(originalTask) {
  return `
Implement a focused fix for the following task:

${originalTask}

Use the diagnostician report as supporting context.
Independently verify the diagnosis before modifying files.
Do not expand the scope beyond the reported problem.
`.trim();
}

function createTestTask(originalTask) {
  return `
Create or update regression tests for the following task:

${originalTask}

Inspect the current implementation and the bug-fixer report.
Run only approved test commands.
Report the commands executed and their real results.
`.trim();
}

function createReviewTask(originalTask) {
  return `
Review the final implementation for the following task:

${originalTask}

Inspect the current repository state, implementation changes,
and available tests. Identify correctness issues, regressions,
security risks, and missing coverage. Do not modify files.
`.trim();
}

function printPipelineSummary(runs) {
  console.log(
    "\nPipeline completed successfully.\n"
  );

  console.table(
    runs.map((run) => ({
      agent: run.agent,
      status: run.status,
      runId: run.id,
      parent:
        run.parentRunId?.slice(-6) ?? "-",
      context:
        run.contextRunId?.slice(-6) ?? "-"
    }))
  );

  console.log(
    "Changes remain uncommitted for human review."
  );
}