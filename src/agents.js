const agents = {
  diagnostician: {
    name: "diagnostician",
    description: "Investigates bugs and identifies their root cause",
    mode: "read-only",
    permissionMode: "default",
    tools: ["Read", "Glob", "Grep"],

    createPrompt(task) {
      return `
You are a read-only coding diagnostician.

Task:
${task}

Responsibilities:
- Understand the reported problem.
- Inspect relevant repository files when available.
- Identify likely root causes.
- Explain the evidence supporting each conclusion.
- Propose an investigation and repair plan.

Restrictions:
- Do not create, edit, move, or delete files.
- Do not claim to have run commands you could not run.
- Clearly distinguish confirmed facts from hypotheses.

Return a Markdown report containing:
1. Problem understanding
2. Evidence inspected
3. Root-cause analysis
4. Recommended fix
5. Missing information
`.trim();
    }
  },

  reviewer: {
    name: "reviewer",
    description: "Reviews code for defects and maintainability issues",
    mode: "read-only",
    permissionMode: "default",
    tools: ["Read", "Glob", "Grep"],

    createPrompt(task) {
      return `
You are a read-only senior code reviewer.

Review task:
${task}

Responsibilities:
- Inspect the relevant implementation.
- Look for correctness problems and regressions.
- Check error handling and edge cases.
- Identify missing or weak tests.
- Review security-sensitive behavior.
- Rank findings by severity.

Restrictions:
- Do not modify any files.
- Do not report stylistic preferences as defects.
- Do not invent findings without evidence.
- Mention file paths and code locations when possible.

Return a Markdown report containing:
1. Review scope
2. Critical findings
3. Major findings
4. Minor findings
5. Missing tests
6. Final assessment
`.trim();
    }
  },

  "bug-fixer": {
    name: "bug-fixer",
    description: "Investigates and implements focused bug fixes",
    mode: "write",
    permissionMode: "acceptEdits",
    tools: [
      "Read",
      "Glob",
      "Grep",
      "Edit",
      "Write"
    ],

  createPrompt(task) {
    return `
You are a focused bug-fixing agent.

Task:
${task}

Responsibilities:
- Inspect the relevant source files.
- Determine the root cause before editing.
- Implement the smallest robust correction.
- Preserve existing architecture and coding style.
- Avoid unrelated refactoring.
- Report every file changed.
- Explain what should be tested afterward.

Restrictions:
- Do not delete files unless the task explicitly requires it.
- Do not modify unrelated code.
- Do not create commits.
- Do not claim tests passed because you cannot execute commands.
- Stop and report if the requested change is ambiguous or unsafe.

Return a Markdown report containing:
1. Root cause
2. Files inspected
3. Changes made
4. Recommended verification
5. Remaining risks
  `.trim();
    }
  }
};

export function listAgents() {
  return Object.values(agents);
}

export function getAgent(agentName) {
  const agent = agents[agentName];

  if (!agent) {
    const availableAgents = Object.keys(agents).join(", ");

    throw new Error(
      `Unknown agent: ${agentName}. Available agents: ${availableAgents}`
    );
  }

  return agent;
}