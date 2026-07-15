import { execFile } from "node:child_process";

function runGit(argumentsList) {
  return new Promise((resolve, reject) => {
    execFile(
      "git",
      argumentsList,
      {
        cwd: process.cwd(),
        encoding: "utf8"
      },
      (error, stdout, stderr) => {
        if (error) {
          reject(
            new Error(
              stderr.trim() ||
              error.message
            )
          );

          return;
        }

        resolve(stdout.trim());
      }
    );
  });
}

export async function getGitStatus() {
  try {
    const branch = await runGit([
      "branch",
      "--show-current"
    ]);

    const changes = await runGit([
      "status",
      "--porcelain"
    ]);

    return {
      isRepository: true,
      branch: branch || "(detached HEAD)",
      isClean: changes.length === 0,
      changes: changes
        ? changes.split("\n")
        : []
    };
  } catch {
    return {
      isRepository: false,
      branch: null,
      isClean: false,
      changes: []
    };
  }
}

export async function requireCleanRepository() {
  const status = await getGitStatus();

  if (!status.isRepository) {
    throw new Error(
      "Write agents require a Git repository"
    );
  }

  if (!status.isClean) {
    throw new Error(
      [
        "Write agents require a clean working tree.",
        "Commit or stash your current changes first.",
        "",
        ...status.changes
      ].join("\n")
    );
  }

  return status;
}