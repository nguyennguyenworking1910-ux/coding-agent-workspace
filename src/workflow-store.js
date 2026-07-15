import fs from "node:fs/promises";
import path from "node:path";

const workflowsDirectory = path.join(
  process.cwd(),
  ".agent-workspace",
  "workflows"
);

export async function createWorkflow(task) {
  await fs.mkdir(workflowsDirectory, {
    recursive: true
  });

  const workflowId = createWorkflowId();

  const workflowDirectory = path.join(
    workflowsDirectory,
    workflowId
  );

  await fs.mkdir(workflowDirectory, {
    recursive: true
  });

  const workflow = {
    id: workflowId,
    task,
    status: "running",
    stages: [],
    repositoryRoot: null,
    worktreePath: null,
    branchName: null,
    baseCommit: null,
    createdAt: new Date().toISOString(),
    completedAt: null,
    error: null
  };

  await fs.writeFile(
    path.join(workflowDirectory, "request.md"),
    `# Pipeline Task\n\n${task}\n`,
    "utf8"
  );

  await saveWorkflow(
    workflowDirectory,
    workflow
  );

  return {
    workflow,
    workflowDirectory
  };
}

export async function addWorkflowStage(
  workflow,
  workflowDirectory,
  run
) {
  workflow.stages.push({
    agent: run.agent,
    runId: run.id,
    status: run.status
  });

  await saveWorkflow(
    workflowDirectory,
    workflow
  );
}

export async function setWorkflowWorktree(
  workflow,
  workflowDirectory,
  worktree
) {
  workflow.repositoryRoot =
    worktree.repositoryRoot;

  workflow.worktreePath =
    worktree.worktreePath;

  workflow.branchName =
    worktree.branchName;

  workflow.baseCommit =
    worktree.baseCommit;

  await saveWorkflow(
    workflowDirectory,
    workflow
  );
}

export async function completeWorkflow(
  workflow,
  workflowDirectory
) {
  workflow.status = "completed";
  workflow.completedAt =
    new Date().toISOString();

  await saveWorkflow(
    workflowDirectory,
    workflow
  );

  await saveWorkflowSummary(
    workflowDirectory,
    workflow
  );
}

export async function failWorkflow(
  workflow,
  workflowDirectory,
  error
) {
  workflow.status = "failed";
  workflow.completedAt =
    new Date().toISOString();

  workflow.error =
    error instanceof Error
      ? error.message
      : String(error);

  await saveWorkflow(
    workflowDirectory,
    workflow
  );

  await saveWorkflowSummary(
    workflowDirectory,
    workflow
  );
}

export async function listWorkflows() {
  try {
    const entries = await fs.readdir(
      workflowsDirectory,
      {
        withFileTypes: true
      }
    );

    const workflows = [];

    for (const entry of entries) {
      if (!entry.isDirectory()) {
        continue;
      }

      const metadataPath = path.join(
        workflowsDirectory,
        entry.name,
        "workflow.json"
      );

      try {
        const content = await fs.readFile(
          metadataPath,
          "utf8"
        );

        workflows.push(
          JSON.parse(content)
        );
      } catch {
        // Ignore invalid workflow directories.
      }
    }

    return workflows.sort(
      (first, second) =>
        second.createdAt.localeCompare(
          first.createdAt
        )
    );
  } catch (error) {
    if (error.code === "ENOENT") {
      return [];
    }

    throw error;
  }
}

export async function findWorkflow(
  workflowId
) {
  const workflows =
    await listWorkflows();

  const matches = workflows.filter(
    (workflow) =>
      workflow.id.startsWith(workflowId) ||
      workflow.id.endsWith(workflowId)
  );

  if (matches.length === 0) {
    throw new Error(
      `Workflow not found: ${workflowId}`
    );
  }

  if (matches.length > 1) {
    throw new Error(
      `Workflow ID is ambiguous: ${workflowId}`
    );
  }

  const workflow = matches[0];

  return {
    workflow,
    workflowDirectory: path.join(
      workflowsDirectory,
      workflow.id
    )
  };
}

async function saveWorkflow(
  workflowDirectory,
  workflow
) {
  await fs.writeFile(
    path.join(
      workflowDirectory,
      "workflow.json"
    ),
    `${JSON.stringify(workflow, null, 2)}\n`,
    "utf8"
  );
}

export async function readWorkflowOutput(
  workflowId
) {
  const { workflowDirectory } =
    await findWorkflow(workflowId);

  const summaryPath = path.join(
    workflowDirectory,
    "summary.md"
  );

  try {
    return await fs.readFile(
      summaryPath,
      "utf8"
    );
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(
        `Workflow ${workflowId} does not have a summary`
      );
    }

    throw error;
  }
}

async function saveWorkflowSummary(
  workflowDirectory,
  workflow
) {
  const summary =
    createWorkflowSummary(workflow);

  await fs.writeFile(
    path.join(
      workflowDirectory,
      "summary.md"
    ),
    summary,
    "utf8"
  );
}

function createWorkflowSummary(workflow) {
  const lines = [
    "# Pipeline Summary",
    "",
    `- Workflow ID: \`${workflow.id}\``,
    `- Status: **${workflow.status}**`,
    `- Created: ${workflow.createdAt}`,
    `- Completed: ${workflow.completedAt ?? "Not completed"}`,
    "",
    "## Original Task",
    "",
    workflow.task,
    "",
    "## Stages",
    ""
  ];

  if (
    !workflow.stages ||
    workflow.stages.length === 0
  ) {
    lines.push(
      "No agent stages were recorded."
    );
  } else {
    lines.push(
      "| Stage | Agent | Status | Run ID |",
      "|---:|---|---|---|"
    );

    workflow.stages.forEach(
      (stage, index) => {
        lines.push(
          `| ${index + 1} | ${stage.agent} | ${stage.status} | \`${stage.runId ?? "-"}\` |`
        );
      }
    );
  }

  if (workflow.error) {
    lines.push(
      "",
      "## Failure",
      "",
      workflow.error
    );
  }

  lines.push(
    "",
    "## Human Review",
    "",
    "Inspect the Git diff, agent reports, and test evidence before committing or merging any changes.",
    ""
  );

  return lines.join("\n");
}

function createWorkflowId() {
  const timestamp = new Date()
    .toISOString()
    .replaceAll(":", "-")
    .replaceAll(".", "-");

  const randomSuffix = Math.random()
    .toString(36)
    .slice(2, 8);

  return `workflow-${timestamp}-${randomSuffix}`;
}