import { runClaude } from "./claude-provider.js";

import {
  createRun,
  completeRun,
  failRun,
  listRuns,
  findRun,
  readRunOutput
} from "./run-store.js";

import {
  listAgents,
  getAgent
} from "./agents.js";

import { 
    getGitStatus,
    requireCleanRepository
} from "./git-utils.js";

const args = process.argv.slice(2);
const command = args[0];

async function main() {
  if (command === "run") {
    const {
        agentName,
        task,
        contextRunId
    } = parseRunArguments(args.slice(1));

    await handleRun(agentName, task, contextRunId);
    return;
  }

  if (command === "runs") {
    await handleListRuns();
    return;
  }

  if (command === "agents") {
    handleListAgents();
    return;
  }

  if (command === "show") {
    await handleShowRun(args[1]);
    return;
  }

  if (command === "output") {
    await handleOutput(args[1]);
    return;
  }

  if (command === "git-status") {
    await handleGitStatus();
    return;
  }

  showHelp();
}

async function handleGitStatus() {
  const status = await getGitStatus();

  if (!status.isRepository) {
    console.log("Current directory is not a Git repository.");
    return;
  }

  console.log(`Branch: ${status.branch}`);
  console.log(`Clean: ${status.isClean ? "yes" : "no"}`);

  if (status.changes.length > 0) {
    console.log("\nUncommitted changes:");

    for (const change of status.changes) {
      console.log(`  ${change}`);
    }
  }
}

function parseRunArguments(runArguments) {
  const agentName = runArguments[0];

  const contextFlagIndex =
    runArguments.indexOf("--context");

  let taskArguments;
  let contextRunId = null;

  if (contextFlagIndex === -1) {
    taskArguments = runArguments.slice(1);
  } else {
    taskArguments = runArguments.slice(
      1,
      contextFlagIndex
    );

    contextRunId =
      runArguments[contextFlagIndex + 1];

    if (!contextRunId) {
      throw new Error(
        "Missing run ID after --context"
      );
    }

    if (
      contextFlagIndex + 2 <
      runArguments.length
    ) {
      throw new Error(
        "--context must be the final option"
      );
    }
  }

  return {
    agentName,
    task: taskArguments.join(" ").trim(),
    contextRunId
  };
}

async function handleRun(
    agentName, 
    task,
    contextRunId,
    options = {}
  ) {
  if (!agentName || !task) {
    throw new Error(
      'Usage: npm start -- run <agent-name> "your task"'
    );
  }

  const agent = getAgent(agentName);

  if (
    agent.mode === "write" &&
    !options.skipGitSafety
  ) {
    const gitStatus = await requireCleanRepository();

    console.log("Write-agent safety check passed.");
    console.log(`Branch: ${gitStatus.branch}`);
  }

  console.log("Coding Agent Workspace");
  console.log("----------------------");
  console.log(`Agent: ${agent.name}`);
  console.log(`Mode: ${agent.mode}`);
  console.log(`Task: ${task}`);

  let parentRunId = null;
  let resolvedContextRunId = null;
  let contextOutput = null;

  if (contextRunId) {
    const { run: contextRun } =
        await findRun(contextRunId);

    if (contextRun.status !== "completed") {
        throw new Error(
        `Context run must be completed: ${contextRun.id}`
        );
    }

    contextOutput = await readRunOutput(
        contextRun.id
    );

    resolvedContextRunId = contextRun.id;

    parentRunId =
        contextRun.parentRunId ??
        contextRun.id;

    console.log(
        `Context run: ${resolvedContextRunId}`
    );

    console.log(
        `Parent run: ${parentRunId}`
    );
  }

  const { run, runDirectory } = await createRun(
    task,
    agent.name,
    {
        parentRunId,
        contextRunId: resolvedContextRunId
    }
  );

  console.log(`Run ID: ${run.id}`);

  const basePrompt = agent.createPrompt(task);

  const prompt = buildPromptWithContext(
    basePrompt,
    contextOutput,
    resolvedContextRunId
  )

  try {
    const response = await runClaude(
      prompt,
      agent.tools,
      agent.permissionMode,
      agent.allowedTools
    );

    await completeRun(
      run,
      runDirectory,
      response
    );

    console.log("\n\nAgent completed successfully.");
    console.log(`Output saved to: ${runDirectory}`);

    return {
        run,
        runDirectory,
        response
    };
  } catch (error) {
    await failRun(
      run,
      runDirectory,
      error
    );

    throw error;
  }
}

function handleListAgents() {
  const agents = listAgents();

  console.table(
    agents.map((agent) => ({
      name: agent.name,
      mode: agent.mode,
      description: agent.description,
      tools: agent.tools.join(", ")
    }))
  );
}

async function handleListRuns() {
  const runs = await listRuns();

  if (runs.length === 0) {
    console.log("No agent runs found.");
    return;
  }

  console.log("Agent run history\n");

  console.table(
    runs.map((run) => ({
      id: run.id,
      agent: run.agent ?? "unknown",
      status: run.status,
      parent: shortenRunId(run.parentRunId),
      context: shortenRunId(run.contextRunId),
      created: run.createdAt,
      task: shorten(run.task, 50)
    }))
  );
}

async function handleShowRun(runId) {
  requireRunId(runId, "show");

  const { run, runDirectory } = await findRun(runId);

  console.log(JSON.stringify(run, null, 2));
  console.log(`\nDirectory: ${runDirectory}`);
}

async function handleOutput(runId) {
  requireRunId(runId, "output");

  const output = await readRunOutput(runId);
  console.log(output);
}

function requireRunId(runId, commandName) {
  if (!runId) {
    throw new Error(
      `Usage: npm start -- ${commandName} <run-id>`
    );
  }
}

function shorten(text, maximumLength) {
  if (text.length <= maximumLength) {
    return text;
  }

  return `${text.slice(0, maximumLength - 3)}...`;
}

function buildPromptWithContext(
  basePrompt,
  contextOutput,
  contextRunId
) {
  if (!contextOutput) {
    return basePrompt;
  }

  return `
${basePrompt}

## Previous Agent Context

The following report was produced by run:
${contextRunId}

Treat this report as supporting context only.

You must:

- Independently verify its claims against the repository.
- Not assume its findings are correct.
- Use relevant findings to continue the assigned task.
- Clearly mention any claim that cannot be verified.

<previous-agent-report>
${contextOutput}
</previous-agent-report>
`.trim();
}

function shortenRunId(runId) {
  if (!runId) {
    return "-";
  }

  return runId.slice(-6);
}

function showHelp() {
  console.log(`
Coding Agent Workspace

Commands:
  npm start -- agents
  npm start -- run <agent-name> "your task" [--context <run-id>]
  npm start -- runs
  npm start -- show <run-id>
  npm start -- output <run-id>
  npm start -- git-status
`.trim());
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});