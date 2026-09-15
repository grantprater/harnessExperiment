// Offline contract checks: no server, browser, or game is started.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let expiry;
let delay;
let clears = 0;
let stops = 0;
const context = {
  require(name) {
    if (name === 'http') return { createServer: () => ({ listen() {} }) };
    throw new Error('Optional live dependency disabled in test');
  },
  process: { env: {} }, console,
  setTimeout(fn, ms) { expiry = fn; delay = ms; return 1; },
  clearTimeout() {},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../reticle/adapters/minecraft_bridge/index.js'), 'utf8'), context);
context.fakeBot = {
  entity: { yaw: 0, pitch: 0, position: { x: 0, y: 64, z: 0 } },
  health: 20, targetDigBlock: {},
  clearControlStates() { clears++; },
  stopDigging() { stops++; },
  deactivateItem() {},
};
vm.runInContext('bot = fakeBot', context);
assert.equal(vm.runInContext('getBotState().inventory', context), null);
context.fakeBot.inventory = { slots: [{ name: 'oak_log', count: 2 }, null] };
assert.equal(vm.runInContext('getBotState().inventory.oak_log', context), 2);
assert.equal(vm.runInContext('getBotState().source', context), 'mineflayer_live_state');
vm.runInContext('heldButtons.add("left"); renewInputLease()', context);
assert.equal(delay, 2000);
expiry();
assert.equal(clears, 1);
assert.equal(stops, 1);
assert.equal(vm.runInContext('heldButtons.size', context), 0);
console.log('Bridge state and input expiry contracts passed');
