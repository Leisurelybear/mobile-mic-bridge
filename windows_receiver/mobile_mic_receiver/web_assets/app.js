(() => {
  const TARGET_RATE = 48000;
  const FRAME_SAMPLES = 960; // 20 ms @ 48 kHz
  const MAX_QUEUE_FRAMES = 8;
  const Dsp = globalThis.MobileMicDsp;
  if (!Dsp) {
    console.error('MobileMicDsp missing — load /dsp.js before /app.js');
  }

  const els = {
    status: document.getElementById('status'),
    error: document.getElementById('error'),
    bgWarn: document.getElementById('bg-warn'),
    feedbackWarn: document.getElementById('feedback-warn'),
    start: document.getElementById('btn-start'),
    pause: document.getElementById('btn-pause'),
    stop: document.getElementById('btn-stop'),
    gain: document.getElementById('gain'),
    gainLabel: document.getElementById('gain-label'),
    echo: document.getElementById('echo'),
    noise: document.getElementById('noise'),
    agc: document.getElementById('agc'),
    feedback: document.getElementById('feedback'),
    level: document.getElementById('level'),
  };

  let state = 'idle';
  let sessionId = 0;
  let token = new URLSearchParams(location.search).get('token') || '';
  let gain = 1.0;
  let ws = null;
  let audioContext = null;
  let mediaStream = null;
  let workletNode = null;
  let sourceNode = null;
  let scriptNode = null;
  let silentGain = null;
  let wakeLock = null;
  let sendQueue = [];
  let pcmCarry = new Float32Array(0);
  let feedbackGuard = {
    highCount: 0,
    lowCount: 0,
    duckGain: 1,
    ducked: false,
  };

  function setStatus(text) {
    els.status.textContent = `状态：${text}`;
  }

  function setError(message) {
    if (!message) {
      els.error.hidden = true;
      els.error.textContent = '';
      return;
    }
    els.error.hidden = false;
    els.error.textContent = message;
  }

  function setFeedbackWarn(show) {
    if (!els.feedbackWarn) return;
    els.feedbackWarn.hidden = !show;
  }

  function resetFeedbackGuard() {
    feedbackGuard = {
      highCount: 0,
      lowCount: 0,
      duckGain: 1,
      ducked: false,
    };
    setFeedbackWarn(false);
  }

  function setButtons() {
    els.start.disabled =
      state === 'streaming' ||
      state === 'connecting' ||
      state === 'requesting_mic' ||
      state === 'paused';
    els.pause.disabled = state !== 'streaming' && state !== 'paused';
    els.pause.textContent = state === 'paused' ? '继续' : '暂停';
    els.stop.disabled = state === 'idle';
  }

  function deviceLabel() {
    const ua = navigator.userAgent || '';
    if (/Android/i.test(ua)) return 'web-android';
    if (/iPhone|iPad|iPod/i.test(ua)) return 'web-ios';
    return 'web-other';
  }

  function audioConstraints() {
    // Prefer ideal+exact-ish constraints so browsers keep AEC/NS on when
    // possible. PC-speaker echo is acoustic; phone AEC only partially helps.
    return {
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: { ideal: !!els.echo.checked },
        noiseSuppression: { ideal: !!els.noise.checked },
        autoGainControl: { ideal: !!els.agc.checked },
        // Avoid Bluetooth SCO / speakerphone routes that worsen feedback when
        // the phone is near a PC speaker (best-effort; browsers may ignore).
        voiceIsolation: els.noise.checked ? { ideal: true } : undefined,
      },
      video: false,
    };
  }

  function resampleLinear(input, fromRate, toRate) {
    if (fromRate === toRate) return input;
    const ratio = fromRate / toRate;
    const outLength = Math.floor(input.length / ratio);
    if (outLength <= 0) return new Float32Array(0);
    const out = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const src = i * ratio;
      const i0 = Math.floor(src);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = src - i0;
      out[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return out;
  }

  function peakOf(floatSamples) {
    let peak = 0;
    for (let i = 0; i < floatSamples.length; i++) {
      const a = Math.abs(floatSamples[i]);
      if (a > peak) peak = a;
    }
    return peak;
  }

  function enqueuePcm(arrayBuffer) {
    sendQueue.push(arrayBuffer);
    while (sendQueue.length > MAX_QUEUE_FRAMES) sendQueue.shift();
    flushQueue();
  }

  function flushQueue() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    while (sendQueue.length) {
      ws.send(sendQueue.shift());
    }
  }

  function handleCaptureFloats(floatSamples, sid) {
    if (sid !== sessionId || state !== 'streaming') return;
    const rate = audioContext ? audioContext.sampleRate : TARGET_RATE;
    const resampled = resampleLinear(floatSamples, rate, TARGET_RATE);
    const inputPeak = peakOf(resampled);
    els.level.value = inputPeak;

    if (els.feedback && els.feedback.checked && Dsp) {
      const result = Dsp.updateFeedbackGuard(feedbackGuard, inputPeak);
      feedbackGuard = result.guard;
      if (result.justDucked) setFeedbackWarn(true);
      if (!feedbackGuard.ducked) setFeedbackWarn(false);
    } else if (!els.feedback || !els.feedback.checked) {
      if (feedbackGuard.duckGain !== 1 || feedbackGuard.ducked) {
        resetFeedbackGuard();
      }
    }

    const merged = new Float32Array(pcmCarry.length + resampled.length);
    merged.set(pcmCarry, 0);
    merged.set(resampled, pcmCarry.length);

    let offset = 0;
    while (offset + FRAME_SAMPLES <= merged.length) {
      const frame = merged.subarray(offset, offset + FRAME_SAMPLES);
      if (Dsp) {
        const encoded = Dsp.floatToPcm16Limited(
          frame,
          gain,
          feedbackGuard.duckGain,
          0.89
        );
        enqueuePcm(encoded.buffer);
      } else {
        // Fallback without DSP module: hard clip only.
        const buffer = new ArrayBuffer(frame.length * 2);
        const view = new DataView(buffer);
        const duck = feedbackGuard.duckGain || 1;
        for (let i = 0; i < frame.length; i++) {
          let s = frame[i] * gain * duck;
          if (s > 1) s = 1;
          if (s < -1) s = -1;
          view.setInt16(i * 2, (s * 32767) | 0, true);
        }
        enqueuePcm(buffer);
      }
      offset += FRAME_SAMPLES;
    }
    pcmCarry = merged.subarray(offset);
  }

  async function requestWakeLock() {
    try {
      if (navigator.wakeLock && navigator.wakeLock.request) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => {
          wakeLock = null;
        });
      }
    } catch (_) {
      /* optional */
    }
  }

  async function releaseWakeLock() {
    try {
      if (wakeLock) await wakeLock.release();
    } catch (_) {
      /* ignore */
    }
    wakeLock = null;
  }

  async function openMic() {
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
      const insecure =
        location.protocol !== 'https:' && location.hostname !== 'localhost';
      if (insecure) {
        throw new Error(
          '当前页面不是 HTTPS，手机浏览器禁止访问麦克风。请用接收端生成的 https:// 二维码打开，并在证书警告页选择继续访问。'
        );
      }
      throw new Error(
        '当前浏览器不支持麦克风采集（navigator.mediaDevices 不可用）。'
      );
    }
    mediaStream = await mediaDevices.getUserMedia(audioConstraints());
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioCtx({ sampleRate: TARGET_RATE });
    if (audioContext.state === 'suspended') await audioContext.resume();
    sourceNode = audioContext.createMediaStreamSource(mediaStream);
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;

    const sid = sessionId;
    try {
      await audioContext.audioWorklet.addModule('/worklet.js');
      workletNode = new AudioWorkletNode(audioContext, 'capture-processor');
      workletNode.port.onmessage = (ev) => {
        handleCaptureFloats(ev.data, sid);
      };
      sourceNode.connect(workletNode);
      // Keep graph alive without audible local monitor (avoids phone speaker echo).
      workletNode.connect(silentGain);
      silentGain.connect(audioContext.destination);
    } catch (_) {
      const bufferSize = 4096;
      scriptNode = audioContext.createScriptProcessor(bufferSize, 1, 1);
      scriptNode.onaudioprocess = (ev) => {
        const input = ev.inputBuffer.getChannelData(0);
        handleCaptureFloats(new Float32Array(input), sid);
      };
      sourceNode.connect(scriptNode);
      scriptNode.connect(silentGain);
      silentGain.connect(audioContext.destination);
    }
  }

  function stopMicOnly() {
    try {
      if (workletNode) workletNode.disconnect();
    } catch (_) {}
    try {
      if (scriptNode) scriptNode.disconnect();
    } catch (_) {}
    try {
      if (sourceNode) sourceNode.disconnect();
    } catch (_) {}
    try {
      if (silentGain) silentGain.disconnect();
    } catch (_) {}
    workletNode = null;
    scriptNode = null;
    sourceNode = null;
    silentGain = null;
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    pcmCarry = new Float32Array(0);
    sendQueue = [];
    els.level.value = 0;
  }

  function closeSocket() {
    if (ws) {
      try {
        ws.onclose = null;
        ws.close();
      } catch (_) {}
    }
    ws = null;
  }

  async function fullCleanup() {
    stopMicOnly();
    closeSocket();
    await releaseWakeLock();
    resetFeedbackGuard();
  }

  function connectWs(sid) {
    return new Promise((resolve, reject) => {
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(`${scheme}//${location.host}/mic`);
      socket.binaryType = 'arraybuffer';
      let settled = false;

      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          try {
            socket.close();
          } catch (_) {}
          reject(new Error('连接超时'));
        }
      }, 5000);

      socket.onopen = () => {
        socket.send(
          JSON.stringify({
            type: 'hello',
            version: 1,
            sampleRate: TARGET_RATE,
            channels: 1,
            format: 'pcm_s16le',
            token: token,
            device: deviceLabel(),
          })
        );
      };

      socket.onmessage = (ev) => {
        if (typeof ev.data !== 'string') return;
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch (_) {
          return;
        }
        if (msg.type === 'ready' && !settled) {
          settled = true;
          clearTimeout(timer);
          resolve(socket);
        } else if (msg.type === 'error' && !settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error(msg.message || '连接被拒绝'));
        }
      };

      socket.onerror = () => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error('WebSocket 错误'));
        }
      };

      socket.onclose = () => {
        if (
          sid === sessionId &&
          (state === 'streaming' || state === 'paused' || state === 'connecting')
        ) {
          state = 'error';
          setStatus('错误');
          setError('连接已断开');
          setButtons();
          fullCleanup();
        }
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error('连接关闭'));
        }
      };
    });
  }

  async function start() {
    if (state !== 'idle' && state !== 'error') return;
    sessionId += 1;
    const sid = sessionId;
    setError('');
    resetFeedbackGuard();
    state = 'requesting_mic';
    setStatus('申请麦克风…');
    setButtons();
    try {
      await openMic();
      if (sid !== sessionId) return;
      state = 'connecting';
      setStatus('连接中…');
      setButtons();
      ws = await connectWs(sid);
      if (sid !== sessionId) return;
      state = 'streaming';
      setStatus('传输中');
      setButtons();
      await requestWakeLock();
    } catch (err) {
      if (sid !== sessionId) return;
      state = 'error';
      setStatus('错误');
      setError(err && err.message ? err.message : String(err));
      setButtons();
      await fullCleanup();
    }
  }

  async function pauseToggle() {
    if (state === 'streaming') {
      stopMicOnly();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'pause' }));
      }
      state = 'paused';
      setStatus('已暂停');
      setButtons();
      return;
    }
    if (state === 'paused') {
      const sid = sessionId;
      try {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          state = 'connecting';
          setStatus('重连中…');
          setButtons();
          ws = await connectWs(sid);
        } else {
          ws.send(JSON.stringify({ type: 'resume' }));
        }
        await openMic();
        if (sid !== sessionId) return;
        state = 'streaming';
        setStatus('传输中');
        setButtons();
        await requestWakeLock();
      } catch (err) {
        state = 'error';
        setStatus('错误');
        setError(err && err.message ? err.message : String(err));
        setButtons();
        await fullCleanup();
      }
    }
  }

  async function stop() {
    sessionId += 1;
    state = 'idle';
    setStatus('空闲');
    setError('');
    setButtons();
    await fullCleanup();
  }

  async function applyTrackConstraints() {
    if (!mediaStream) return;
    const track = mediaStream.getAudioTracks()[0];
    if (!track || !track.applyConstraints) return;
    try {
      await track.applyConstraints({
        echoCancellation: !!els.echo.checked,
        noiseSuppression: !!els.noise.checked,
        autoGainControl: !!els.agc.checked,
      });
    } catch (_) {
      /* some browsers reject partial constraint updates */
    }
  }

  els.start.addEventListener('click', () => {
    start();
  });
  els.pause.addEventListener('click', () => {
    pauseToggle();
  });
  els.stop.addEventListener('click', () => {
    stop();
  });
  els.gain.addEventListener('input', () => {
    gain = Number(els.gain.value) / 100;
    els.gainLabel.textContent = `${els.gain.value}%`;
  });
  els.echo.addEventListener('change', () => applyTrackConstraints());
  els.noise.addEventListener('change', () => applyTrackConstraints());
  els.agc.addEventListener('change', () => applyTrackConstraints());
  if (els.feedback) {
    els.feedback.addEventListener('change', () => {
      if (!els.feedback.checked) resetFeedbackGuard();
    });
  }

  document.addEventListener('visibilitychange', () => {
    els.bgWarn.hidden = document.visibilityState === 'visible';
    if (document.visibilityState === 'visible' && state === 'streaming') {
      requestWakeLock();
      if (audioContext && audioContext.state === 'suspended') {
        audioContext.resume();
      }
    }
  });

  setButtons();
  setStatus('空闲');
})();
