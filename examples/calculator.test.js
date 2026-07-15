import test from 'node:test';
import assert from 'node:assert/strict';

import { add } from './calculator.js';

test('add(2, 3) returns 5', () => {
  assert.equal(add(2, 3), 5);
});
