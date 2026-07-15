import test from "node:test";
import assert from "node:assert/strict";

import {
  parseRunArguments
} from "./run-arguments.js";

test(
  "parses a standalone agent run",
  () => {
    const result = parseRunArguments([
      "diagnostician",
      "Inspect",
      "the",
      "calculator"
    ]);

    assert.deepEqual(result, {
      agentName: "diagnostician",
      task: "Inspect the calculator",
      contextRunId: null
    });
  }
);

test(
  "parses an agent run with context",
  () => {
    const result = parseRunArguments([
      "reviewer",
      "Review",
      "the",
      "diagnosis",
      "--context",
      "run-123"
    ]);

    assert.deepEqual(result, {
      agentName: "reviewer",
      task: "Review the diagnosis",
      contextRunId: "run-123"
    });
  }
);

test(
  "rejects a missing agent name",
  () => {
    assert.throws(
      () => parseRunArguments([]),
      /Missing agent name/
    );
  }
);

test(
  "rejects a missing task",
  () => {
    assert.throws(
      () => parseRunArguments([
        "reviewer"
      ]),
      /Missing agent task/
    );
  }
);

test(
  "rejects a missing context run ID",
  () => {
    assert.throws(
      () => parseRunArguments([
        "reviewer",
        "Review the diagnosis",
        "--context"
      ]),
      /Missing run ID/
    );
  }
);

test(
  "rejects arguments after context ID",
  () => {
    assert.throws(
      () => parseRunArguments([
        "reviewer",
        "Review the diagnosis",
        "--context",
        "run-123",
        "unexpected"
      ]),
      /final option/
    );
  }
);