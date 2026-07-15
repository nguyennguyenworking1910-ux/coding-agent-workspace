export function parseRunArguments(
  runArguments
) {
  const agentName = runArguments[0];

  if (!agentName) {
    throw new Error(
      "Missing agent name"
    );
  }

  const contextFlagIndex =
    runArguments.indexOf("--context");

  let taskArguments;
  let contextRunId = null;

  if (contextFlagIndex === -1) {
    taskArguments =
      runArguments.slice(1);
  } else {
    taskArguments =
      runArguments.slice(
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
      contextFlagIndex + 2 !==
      runArguments.length
    ) {
      throw new Error(
        "--context must be the final option"
      );
    }
  }

  const task =
    taskArguments.join(" ").trim();

  if (!task) {
    throw new Error(
      "Missing agent task"
    );
  }

  return {
    agentName,
    task,
    contextRunId
  };
}