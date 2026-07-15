import test from "node:test";
import assert from "node:assert/strict";

import {
  deriveRunRelationships
} from "./run-context.js";

test(
  "returns empty relationships for a root run",
  () => {
    const result =
      deriveRunRelationships(null);

    assert.deepEqual(result, {
      parentRunId: null,
      contextRunId: null
    });
  }
);

test(
  "uses a root context run as the parent",
  () => {
    const result =
      deriveRunRelationships({
        id: "diagnosis-run",
        parentRunId: null,
        status: "completed"
      });

    assert.deepEqual(result, {
      parentRunId: "diagnosis-run",
      contextRunId: "diagnosis-run"
    });
  }
);

test(
  "inherits the existing parent from a child run",
  () => {
    const result =
      deriveRunRelationships({
        id: "bug-fixer-run",
        parentRunId: "diagnosis-run",
        status: "completed"
      });

    assert.deepEqual(result, {
      parentRunId: "diagnosis-run",
      contextRunId: "bug-fixer-run"
    });
  }
);

test(
  "rejects an incomplete context run",
  () => {
    assert.throws(
      () => deriveRunRelationships({
        id: "running-agent",
        parentRunId: null,
        status: "running"
      }),
      /must be completed/
    );
  }
);

test(
  "rejects context without an ID",
  () => {
    assert.throws(
      () => deriveRunRelationships({
        status: "completed"
      }),
      /does not have an ID/
    );
  }
);