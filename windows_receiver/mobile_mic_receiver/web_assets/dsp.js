/**
 * Pure PCM helpers for the web mic client (no DOM).
 * Loaded as a classic script; attaches to globalThis.MobileMicDsp.
 */
(function (root) {
  'use strict';

  function softLimit(sample, threshold) {
    const t = threshold == null ? 0.89 : threshold;
    const a = Math.abs(sample);
    if (a <= t) return sample;
    const sign = sample < 0 ? -1 : 1;
    // Gentle knee so peaks don't hard-clip into square-wave howl.
    return sign * (t + (1 - t) * Math.tanh((a - t) / (1 - t + 1e-6)));
  }

  function applyGainWithLimit(floatSamples, gainValue, threshold) {
    const out = new Float32Array(floatSamples.length);
    let peak = 0;
    for (let i = 0; i < floatSamples.length; i++) {
      const s = softLimit(floatSamples[i] * gainValue, threshold);
      out[i] = s;
      const a = Math.abs(s);
      if (a > peak) peak = a;
    }
    return { samples: out, peak: peak };
  }

  /**
   * Feedback / howling guard.
   * Counts consecutive high-peak frames; when threshold is hit, multiplies
   * duckGain by duckFactor (clamped to minDuck) and returns a warning flag.
   */
  function updateFeedbackGuard(guard, peak, options) {
    const opts = options || {};
    const highPeak = opts.highPeak == null ? 0.72 : opts.highPeak;
    const holdFrames = opts.holdFrames == null ? 12 : opts.holdFrames; // ~240ms @20ms
    const duckFactor = opts.duckFactor == null ? 0.5 : opts.duckFactor;
    const minDuck = opts.minDuck == null ? 0.15 : opts.minDuck;
    const recoverBelow = opts.recoverBelow == null ? 0.25 : opts.recoverBelow;
    const recoverFrames = opts.recoverFrames == null ? 50 : opts.recoverFrames;
    const recoverStep = opts.recoverStep == null ? 0.05 : opts.recoverStep;

    const next = {
      highCount: guard.highCount || 0,
      lowCount: guard.lowCount || 0,
      duckGain: guard.duckGain == null ? 1 : guard.duckGain,
      ducked: !!guard.ducked,
    };
    let justDucked = false;

    if (peak >= highPeak) {
      next.highCount += 1;
      next.lowCount = 0;
      if (next.highCount >= holdFrames && next.duckGain > minDuck + 1e-6) {
        next.duckGain = Math.max(minDuck, next.duckGain * duckFactor);
        next.highCount = 0;
        next.ducked = true;
        justDucked = true;
      }
    } else if (peak <= recoverBelow) {
      next.highCount = 0;
      next.lowCount += 1;
      if (next.ducked && next.lowCount >= recoverFrames && next.duckGain < 1) {
        next.duckGain = Math.min(1, next.duckGain + recoverStep);
        if (next.duckGain >= 0.999) {
          next.duckGain = 1;
          next.ducked = false;
          next.lowCount = 0;
        }
      }
    } else {
      next.highCount = 0;
      next.lowCount = 0;
    }

    return { guard: next, justDucked: justDucked };
  }

  function floatToPcm16Limited(floatSamples, gainValue, duckGain, threshold) {
    const effective = gainValue * (duckGain == null ? 1 : duckGain);
    const limited = applyGainWithLimit(floatSamples, effective, threshold);
    const buffer = new ArrayBuffer(limited.samples.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < limited.samples.length; i++) {
      let s = limited.samples[i];
      if (s > 1) s = 1;
      if (s < -1) s = -1;
      view.setInt16(i * 2, (s * 32767) | 0, true);
    }
    return { buffer: buffer, peak: limited.peak };
  }

  root.MobileMicDsp = {
    softLimit: softLimit,
    applyGainWithLimit: applyGainWithLimit,
    updateFeedbackGuard: updateFeedbackGuard,
    floatToPcm16Limited: floatToPcm16Limited,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
