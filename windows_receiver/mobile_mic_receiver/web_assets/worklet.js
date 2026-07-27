class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      // Copy because the underlying buffer is reused.
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}

registerProcessor('capture-processor', CaptureProcessor);
