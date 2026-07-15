import test from 'node:test';
import assert from 'node:assert/strict';

import { add } from './calculator.js';

test('add(2, 3) returns 5', () => {
  assert.equal(add(2, 3), 5);
});

// Regression guards against the operator-swap bug (subtraction used instead
// of addition). Commutativity in particular fails for subtraction.
test('add is commutative', () => {
  assert.equal(add(2, 3), add(3, 2));
});

test('add(-4, -6) returns -10', () => {
  assert.equal(add(-4, -6), -10);
});

test('add(5, 0) returns 5 (zero identity)', () => {
  assert.equal(add(5, 0), 5);
});

test('add(1.5, 2.25) returns 3.75', () => {
  assert.equal(add(1.5, 2.25), 3.75);
});
