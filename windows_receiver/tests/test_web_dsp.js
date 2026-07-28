/**
 * Node unit tests for MobileMicDsp (run: node tests/test_web_dsp.js).
 */
const assert = require('assert');
const path = require('path');
const fs = require('fs');

const dspPath = path.join(
  __dirname,
  '..',
  'mobile_mic_receiver',
  'web_assets',
  'dsp.js'
);
const source = fs.readFileSync(dspPath, 'utf8');
// eslint-disable-next-line no-new-func
const run = new Function(`${source}; return globalThis.MobileMicDsp;`);
const Dsp = run();

function testSoftLimitDoesNotExceedUnity() {
  const out = Dsp.softLimit(2.0, 0.89);
  assert.ok(out < 1.0, `expected < 1, got ${out}`);
  assert.ok(out > 0.89, `expected > threshold, got ${out}`);
  assert.strictEqual(Dsp.softLimit(0.5, 0.89), 0.5);
}

function testApplyGainWithLimitReducesHowlPeaks() {
  const input = new Float32Array(16).fill(1.0);
  const { samples, peak } = Dsp.applyGainWithLimit(input, 2.0, 0.89);
  assert.ok(peak <= 1.0, `peak should be limited, got ${peak}`);
  assert.ok(peak < 1.5, 'raw 2.0 gain path must not stay at 2.0');
  for (let i = 0; i < samples.length; i++) {
    assert.ok(Math.abs(samples[i]) <= 1.0 + 1e-9);
  }
}

function testFeedbackGuardDucksOnSustainedHighPeak() {
  let guard = { highCount: 0, lowCount: 0, duckGain: 1, ducked: false };
  let justDucked = false;
  for (let i = 0; i < 12; i++) {
    const result = Dsp.updateFeedbackGuard(guard, 0.9, {
      highPeak: 0.72,
      holdFrames: 12,
      duckFactor: 0.5,
      minDuck: 0.15,
    });
    guard = result.guard;
    justDucked = result.justDucked || justDucked;
  }
  assert.ok(justDucked, 'should duck after sustained high peak');
  assert.ok(guard.ducked);
  assert.ok(guard.duckGain < 1, `duckGain should drop, got ${guard.duckGain}`);
  assert.strictEqual(guard.duckGain, 0.5);
}

function testFeedbackGuardRecoversAfterQuiet() {
  let guard = { highCount: 0, lowCount: 0, duckGain: 0.5, ducked: true };
  for (let i = 0; i < 50; i++) {
    const result = Dsp.updateFeedbackGuard(guard, 0.1, {
      recoverBelow: 0.25,
      recoverFrames: 50,
      recoverStep: 0.05,
    });
    guard = result.guard;
  }
  // One recover step after 50 quiet frames
  assert.ok(guard.duckGain > 0.5, `expected recovery, got ${guard.duckGain}`);
}

function testFloatToPcm16LimitedProducesInt16() {
  const input = new Float32Array([0, 0.5, -0.5, 1.5]);
  const { buffer, peak } = Dsp.floatToPcm16Limited(input, 1.0, 1.0, 0.89);
  assert.strictEqual(buffer.byteLength, 8);
  assert.ok(peak < 1.0);
  const view = new DataView(buffer);
  assert.strictEqual(view.getInt16(0, true), 0);
  assert.ok(view.getInt16(2, true) > 0);
  assert.ok(view.getInt16(4, true) < 0);
}

const tests = [
  testSoftLimitDoesNotExceedUnity,
  testApplyGainWithLimitReducesHowlPeaks,
  testFeedbackGuardDucksOnSustainedHighPeak,
  testFeedbackGuardRecoversAfterQuiet,
  testFloatToPcm16LimitedProducesInt16,
];

let failed = 0;
for (const t of tests) {
  try {
    t();
    console.log(`ok - ${t.name}`);
  } catch (err) {
    failed += 1;
    console.error(`FAIL - ${t.name}: ${err && err.message ? err.message : err}`);
  }
}
if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
console.log(`${tests.length} passed`);
