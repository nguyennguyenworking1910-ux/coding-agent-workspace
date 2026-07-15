import { runClaude } from "./claude-provider.js";

import {
  createRun,
  completeRun,
  failRun,
  findRun,
  readRunOutput
} from "./run-store.js";

import { getAgent } from "./agents.js";

import {
  requireCleanRepository
} from "./git-utils.js";

import {
  deriveRunRelationships
} from "./run-context.js";

export async function executeAgentRun(
  agentName,
  task,
  contextRunId = null,
  options = {}
) {
  if (!agentName || !task) {
    throw new Error(
      "Agent name and task are required"
    );
  }

  const agent = getAgent(agentName);

  if (
    agent.mode === "write" &&
    !options.skipGitSafety
  ) {
    const gitStatus =
      await requireCleanRepository();

    console.log(
      "Write-agent safety check passed."
    );

    console.log(
      `Branch: ${gitStatus.branch}`
    );
  }

  let contextOutput = null;
  let contextRun = null;

  if (contextRunId) {
    const contextResult =
        await findRun(contextRunId);

    contextRun = contextResult.run;

    contextOutput = await readRunOutput(
        contextRun.id
    );
  }

  const relationships =
    deriveRunRelationships(contextRun);

  const {
    parentRunId,
    contextRunId: resolvedContextRunId
  } = relationships;

  console.log("Coding Agent Workspace");
  console.log("----------------------");
  console.log(`Agent: ${agent.name}`);
  console.log(`Mode: ${agent.mode}`);
  console.log(`Task: ${task}`);

  if (resolvedContextRunId) {
    console.log(
      `Context run: ${resolvedContextRunId}`
    );

    console.log(
      `Parent run: ${parentRunId}`
    );
  }

  const { run, runDirectory } =
    await createRun(
      task,
      agent.name,
      {
        parentRunId,
        contextRunId: resolvedContextRunId
      }
    );

  console.log(`Run ID: ${run.id}`);

  const basePrompt =
    agent.createPrompt(task);

  const prompt = buildPromptWithContext(
    basePrompt,
    contextOutput,
    resolvedContextRunId
  );

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

    console.log(
      "\n\nAgent completed successfully."
    );

    console.log(
      `Output saved to: ${runDirectory}`
    );

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