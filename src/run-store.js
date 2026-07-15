import fs from "node:fs/promises";
import path from "node:path";

const workspaceDirectory = path.join(
  process.cwd(),
  ".agent-workspace"
);

const runsDirectory = path.join(
  workspaceDirectory,
  "runs"
);

export async function createRun(
    task, 
    agentName,
    options = {}
) {
  await fs.mkdir(runsDirectory, {
    recursive: true
  });

  const runId = createRunId();
  const runDirectory = path.join(runsDirectory, runId);

  await fs.mkdir(runDirectory, {
    recursive: true
  });

  const run = {
    id: runId,
    agent: agentName,
    task,
    parentRunId: options.parentRunId ?? null,
    contextRunId: options.contextRunId ?? null,
    status: "running",
    createdAt: new Date().toISOString(),
    completedAt: null,
    error: null
  };

  await fs.writeFile(
    path.join(runDirectory, "request.md"),
    `# Task\n\n${task}\n`,
    "utf8"
  );

  await saveRunMetadata(runDirectory, run);

  return {
    run,
    runDirectory
  };
}

export async function completeRun(
  run,
  runDirectory,
  response
) {
  run.status = "completed";
  run.completedAt = new Date().toISOString();

  await fs.writeFile(
    path.join(runDirectory, "response.md"),
    response,
    "utf8"
  );

  await saveRunMetadata(runDirectory, run);
}

export async function failRun(
  run,
  runDirectory,
  error
) {
  run.status = "failed";
  run.completedAt = new Date().toISOString();
  run.error = error.message;

  await saveRunMetadata(runDirectory, run);
}

export async function listRuns() {
  try {
    const entries = await fs.readdir(runsDirectory, {
      withFileTypes: true
    });

    const runs = [];

    for (const entry of entries) {
      if (!entry.isDirectory()) {
        continue;
      }

      const metadataPath = path.join(
        runsDirectory,
        entry.name,
        "run.json"
      );

      try {
        const content = await fs.readFile(
          metadataPath,
          "utf8"
        );

        runs.push(JSON.parse(content));
      } catch {
        // Ignore invalid or incomplete run directories.
      }
    }

    return runs.sort((first, second) =>
      second.createdAt.localeCompare(first.createdAt)
    );
  } catch (error) {
    if (error.code === "ENOENT") {
      return [];
    }

    throw error;
  }
}

export async function findRun(runId) {
  const runs = await listRuns();

  const matches = runs.filter((run) =>
    run.id.startsWith(runId)
  );

  if (matches.length === 0) {
    throw new Error(`Run not found: ${runId}`);
  }

  if (matches.length > 1) {
    throw new Error(
      `Run ID is ambiguous: ${runId}`
    );
  }

  const run = matches[0];

  return {
    run,
    runDirectory: path.join(runsDirectory, run.id)
  };
}

export async function readRunOutput(runId) {
  const { runDirectory } = await findRun(runId);

  const outputPath = path.join(
    runDirectory,
    "response.md"
  );

  try {
    return await fs.readFile(outputPath, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(
        `Run ${runId} does not have an output file`
      );
    }

    throw error;
  }
}

async function saveRunMetadata(runDirectory, run) {
  await fs.writeFile(
    path.join(runDirectory, "run.json"),
    `${JSON.stringify(run, null, 2)}\n`,
    "utf8"
  );
}

function createRunId() {
  const timestamp = new Date()
    .toISOString()
    .replaceAll(":", "-")
    .replaceAll(".", "-");

  const randomSuffix = Math.random()
    .toString(36)
    .slice(2, 8);

  return `${timestamp}-${randomSuffix}`;
}