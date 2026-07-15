import {
  listRuns,
  findRun,
  readRunOutput
} from "./run-store.js";

import {
  listAgents
} from "./agents.js";

import { 
    getGitStatus
} from "./git-utils.js";

import {
  executeAgentRun
} from "./agent-runner.js";

import {
  parseRunArguments
} from "./run-arguments.js";

import {
  executePipeline
} from "./pipeline-runner.js";

const args = process.argv.slice(2);
const command = args[0];

async function main() {
  if (command === "run") {
    const {
        agentName,
        task,
        contextRunId
    } = parseRunArguments(args.slice(1));

    await executeAgentRun(agentName, task, contextRunId);
    return;
  }

  if (command === "pipeline") {
    const task =
        args.slice(1).join(" ").trim();

    if (!task) {
        throw new Error(
        'Usage: npm start -- pipeline "your task"'
        );
    }

    await executePipeline(task);
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
  npm start -- pipeline "your task"
`.trim());
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});