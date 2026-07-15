import { spawn } from "node:child_process";

export function runClaude(
    prompt,
    tools,
    permissionMode = "default",
    allowedTools = []
) {
  return new Promise((resolve, reject) => {
    const args = [
      "--print",
      "--tools",
      tools.join(","),
      "--permission-mode",
      permissionMode,
      "--output-format",
      "text"
    ];

    if (allowedTools.length > 0) {
        args.push(
            "--allowedTools",
            ...allowedTools
        );
    }

    console.log("\nStarting Claude...\n");

    const child = spawn("claude", args, {
      shell: false,
      stdio: ["pipe", "pipe", "pipe"]
    });

    let output = "";
    let errorOutput = "";

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      output += text;
      process.stdout.write(text);
    });

    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      errorOutput += text;
      process.stderr.write(text);
    });

    child.on("error", (error) => {
      reject(
        new Error(`Could not start Claude Code: ${error.message}`)
      );
    });

    child.on("close", (exitCode) => {
      if (exitCode === 0) {
        resolve(output);
      } else {
        reject(
          new Error(
            `Claude Code exited with code ${exitCode}\n${errorOutput}`
          )
        );
      }
    });

    child.stdin.write(prompt);
    child.stdin.end();
  });
}