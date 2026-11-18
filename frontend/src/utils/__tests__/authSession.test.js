import test from 'node:test';
import assert from 'node:assert/strict';
import { isRejectedSession } from '../authSession.js';
test('initial profile lookup only invalidates server-rejected credentials', () => {
 for (const status of [401,403]) assert.equal(isRejectedSession({response:{status}}),true);
 for (const error of [{code:'ERR_NETWORK'},{code:'ERR_CANCELED'},{response:{status:503}},null]) assert.equal(isRejectedSession(error),false);
});
