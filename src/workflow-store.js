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