export function deriveRunRelationships(
  contextRun
) {
  if (!contextRun) {
    return {
      parentRunId: null,
      contextRunId: null
    };
  }

  if (!contextRun.id) {
    throw new Error(
      "Context run does not have an ID"
    );
  }

  if (contextRun.status !== "completed") {
    throw new Error(
      `Context run must be completed: ${contextRun.id}`
    );
  }

  return {
    parentRunId:
      contextRun.parentRunId ??
      contextRun.id,

    contextRunId: contextRun.id
  };
}