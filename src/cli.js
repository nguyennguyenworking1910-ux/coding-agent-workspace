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
    const agentName = args[1];
    const task = args.slice(2).join(" ");

    await handleRun(agentName, task);
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

async function handleRun(agentName, task) {
  if (!agentName || !task) {
    throw new Error(
      'Usage: npm start -- run <agent-name> "your task"'
    );
  }

  const agent = getAgent(agentName);

  if (agent.mode === "write") {
    const gitStatus = await requireCleanRepository();

    console.log("Write-agent safety check passed.");
    console.log(`Branch: ${gitStatus.branch}`);
  }

  console.log("Coding Agent Workspace");
  console.log("----------------------");
  console.log(`Agent: ${agent.name}`);
  console.log(`Mode: ${agent.mode}`);
  console.log(`Task: ${task}`);

  const { run, runDirectory } = await createRun(
    task,
    agent.name
  );

  console.log(`Run ID: ${run.id}`);

  const prompt = agent.createPrompt(task);

  try {
    const response = await runClaude(
      prompt,
      agent.tools,
      agent.permissionMode
    );

    await completeRun(
      run,
      runDirectory,
      response
    );

    console.log("\n\nAgent completed successfully.");
    console.log(`Output saved to: ${runDirectory}`);
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

function showHelp() {
  console.log(`
Coding Agent Workspace

Commands:
  npm start -- agents
  npm start -- run <agent-name> "your task"
  npm start -- runs
  npm start -- show <run-id>
  npm start -- output <run-id>
  npm start -- git status
`.trim());
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});