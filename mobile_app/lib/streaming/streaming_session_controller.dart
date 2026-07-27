import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:record/record.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../audio_gain.dart';
import 'platform_audio_events.dart';
import 'streaming_session_state.dart';

const int streamingSampleRate = 48000;
const int streamingChannels = 1;

class BridgeException implements Exception {
  const BridgeException(this.message);
  final String message;
  @override
  String toString() => message;
}

class StreamingTarget {
  const StreamingTarget({
    required this.host,
    required this.port,
    required this.token,
  });
  final String host;
  final int port;
  final String token;
}

enum CaptureState { recording, paused, stopped }

abstract interface class AudioCapture {
  Stream<CaptureState> get stateChanges;
  Future<bool> hasPermission();
  Future<Stream<List<int>>> startStream(String targetLabel);
  Future<bool> isRecording();
  Future<void> resumeAfterInterruption();
  Future<void> stop();
  Future<void> dispose();
}

abstract interface class StreamingSocket {
  bool get isOpen;
  Stream<dynamic> get messages;
  void add(Object data);
  Future<void> close();
}

abstract interface class StreamingSocketFactory {
  Future<StreamingSocket> connect(Uri uri);
}

abstract interface class SessionWakelock {
  Future<void> enable();
  Future<void> disable();
}

class StreamingSessionController extends ChangeNotifier {
  StreamingSessionController({
    AudioCapture? audioCapture,
    StreamingSocketFactory? socketFactory,
    SessionWakelock? wakelock,
    PlatformAudioResources? platformAudioResources,
  })  : _audioCapture = audioCapture ?? RecordAudioCapture(),
        _socketFactory = socketFactory ?? IoStreamingSocketFactory(),
        _wakelock = wakelock ?? WakelockSession(),
        _platformAudioResources =
            platformAudioResources ?? MethodChannelPlatformAudioResources();

  final AudioCapture _audioCapture;
  final StreamingSocketFactory _socketFactory;
  final SessionWakelock _wakelock;
  final PlatformAudioResources _platformAudioResources;
  StreamingSessionState _state = const StreamingSessionState();
  StreamingSessionState get state => _state;

  StreamingTarget? _target;
  StreamingSocket? _socket;
  StreamSubscription<dynamic>? _socketSubscription;
  StreamSubscription<List<int>>? _audioSubscription;
  StreamSubscription<CaptureState>? _captureStateSubscription;
  StreamSubscription<PlatformAudioEvent>? _platformEventSubscription;
  Future<void>? _pendingRecorderStart;
  Future<void> _controlTail = Future<void>.value();
  Timer? _durationTimer;
  DateTime? _captureStartedAt;
  Duration _capturedDuration = Duration.zero;
  int _sessionId = 0;
  bool _wakelockEnabled = false;
  bool _platformAudioStarted = false;
  bool _userPauseRequested = false;
  bool _detachedCleanupRequested = false;
  bool _cleanupInProgress = false;
  bool _disposed = false;

  void setGain(double gain) =>
      _emit(_state.copyWith(gain: gain.clamp(0, 2).toDouble()));

  Future<void> start(StreamingTarget target) => _serialize(() => _start(target));

  Future<void> pause() {
    _userPauseRequested = true;
    return _serialize(_pause);
  }

  Future<void> resume() => _serialize(_resume);

  Future<void> stop() {
    _userPauseRequested = false;
    return _serialize(() => _stop(emitIdle: true));
  }

  void handleLifecycleState(AppLifecycleState lifecycleState) {
    final visibility = appVisibilityForLifecycle(lifecycleState);
    _emit(_state.copyWith(appVisibility: visibility));
    if (visibility == AppVisibility.detached) {
      if (_detachedCleanupRequested) return;
      _detachedCleanupRequested = true;
      unawaited(_serialize(() => _stop(emitIdle: false)));
    } else if (visibility == AppVisibility.background &&
        (_state.bridgeState == BridgeState.connecting ||
            _state.bridgeState == BridgeState.resuming)) {
      unawaited(_serialize(_cancelIncompleteStartup));
    } else if (visibility == AppVisibility.foreground) {
      unawaited(_serialize(_validateForegroundSession));
    }
  }

  void handlePlatformAudioEvent(PlatformAudioEvent event) {
    switch (event.type) {
      case PlatformAudioEventType.interruptionBegan:
        _markInterrupted();
        break;
      case PlatformAudioEventType.interruptionEnded:
        if (event.canResume && !_userPauseRequested) {
          unawaited(_serialize(_resumeAfterInterruption));
        } else if (!_userPauseRequested &&
            _state.bridgeState == BridgeState.streaming) {
          _captureFailed('系统不允许中断后继续录音，请重新开始');
        }
        break;
      case PlatformAudioEventType.routeChanged:
        if (_state.bridgeState == BridgeState.streaming) {
          _emit(_state.copyWith(status: '音频输入设备已切换'));
        }
        break;
      case PlatformAudioEventType.microphoneUnavailable:
        _captureFailed('麦克风不可用，请检查权限或音频输入设备');
        break;
    }
  }

  Future<void> _start(StreamingTarget target) async {
    if (_state.appVisibility != AppVisibility.foreground) {
      _setError('请回到前台后再开始传输');
      return;
    }
    if (_state.bridgeState != BridgeState.idle &&
        _state.bridgeState != BridgeState.error) {
      return;
    }
    if (target.host.isEmpty || target.port < 1 || target.port > 65535) {
      _setError('IP 地址或端口无效');
      return;
    }
    final sessionId = ++_sessionId;
    _target = target;
    _userPauseRequested = false;
    _capturedDuration = Duration.zero;
    _emit(_state.copyWith(
      bridgeState: BridgeState.connecting,
      status: '正在连接 Windows…',
      duration: Duration.zero,
      userPaused: false,
      interruptionState: InterruptionState.none,
    ));
    try {
      _ensureCaptureStateSubscription();
      _ensurePlatformEventSubscription();
      await _ensurePermissions();
      await _connectAndHandshake(sessionId, target);
      if (!_isCurrent(sessionId)) return;
      if (_state.appVisibility != AppVisibility.foreground) {
        await _stop(emitIdle: true, status: '已取消后台启动');
        return;
      }
      await _startPlatformAudio(sessionId, target.host);
      if (!await _startAudioCapture(sessionId, target.host)) return;
      await _enableWakelock(sessionId);
      if (!_isCurrent(sessionId)) return;
      _beginDurationTracking();
      _emit(_state.copyWith(
        bridgeState: BridgeState.streaming,
        status: '麦克风正在传输',
      ));
    } on TimeoutException {
      if (_isCurrent(sessionId)) {
        await _failAndCleanup('连接超时，请检查 IP、防火墙和端口', sessionId);
      }
    } catch (error) {
      if (_isCurrent(sessionId)) {
        await _failAndCleanup(_safeError('连接失败', error), sessionId);
      }
    }
  }

  Future<void> _pause() async {
    if (_state.bridgeState != BridgeState.streaming) return;
    final sessionId = _sessionId;
    _emit(_state.copyWith(status: '正在暂停录音…', userPaused: true));
    _finishDurationTracking();
    await _pendingRecorderStart;
    await _stopCapture();
    await _stopPlatformAudio();
    await _disableWakelock();
    if (!_isCurrent(sessionId)) return;
    _sendControl('pause');
    _emit(_state.copyWith(
      bridgeState: BridgeState.paused,
      status: '麦克风已暂停',
      userPaused: true,
      interruptionState: InterruptionState.none,
    ));
  }

  Future<void> _resume() async {
    if (_state.bridgeState != BridgeState.paused) return;
    if (_state.appVisibility != AppVisibility.foreground) {
      _emit(_state.copyWith(status: '请回到前台后继续录音'));
      return;
    }
    final target = _target;
    if (target == null) {
      _setError('连接信息已丢失，请重新开始');
      return;
    }
    final sessionId = _sessionId;
    _emit(_state.copyWith(
      bridgeState: BridgeState.resuming,
      status: '正在继续录音…',
    ));
    try {
      await _ensurePermissions();
      if (_socket?.isOpen != true) await _connectAndHandshake(sessionId, target);
      if (!_isCurrent(sessionId)) return;
      if (_state.appVisibility != AppVisibility.foreground) {
        _emit(_state.copyWith(
          bridgeState: BridgeState.paused,
          status: '已取消后台继续',
        ));
        return;
      }
      _sendControl('resume');
      await _startPlatformAudio(sessionId, target.host);
      if (!await _startAudioCapture(sessionId, target.host)) return;
      await _enableWakelock(sessionId);
      if (!_isCurrent(sessionId)) return;
      _userPauseRequested = false;
      _beginDurationTracking();
      _emit(_state.copyWith(
        bridgeState: BridgeState.streaming,
        status: '麦克风正在传输',
        userPaused: false,
      ));
    } catch (error) {
      if (!_isCurrent(sessionId)) return;
      await _stopCapture();
      await _stopPlatformAudio();
      await _disableWakelock();
      _userPauseRequested = true;
      _emit(_state.copyWith(
        bridgeState: BridgeState.paused,
        status: _safeError('继续失败', error),
        userPaused: true,
      ));
    }
  }

  Future<void> _connectAndHandshake(
    int sessionId,
    StreamingTarget target,
  ) async {
    await _closeSocket();
    final socketHost = target.host.contains(':') && !target.host.startsWith('[')
        ? '[${target.host}]'
        : target.host;
    // Prefer wss for the receiver-hosted self-signed TLS endpoint; fall
    // back to plain ws if the secure handshake is refused/unavailable.
    StreamingSocket? socket;
    Object? lastError;
    for (final scheme in <String>['wss', 'ws']) {
      try {
        socket = await _socketFactory
            .connect(Uri.parse('$scheme://$socketHost:${target.port}/mic'))
            .timeout(const Duration(seconds: 8));
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (socket == null) {
      throw BridgeException(_safeError('连接失败', lastError ?? 'unknown'));
    }
    if (!_isCurrent(sessionId)) {
      await socket.close();
      return;
    }
    _socket = socket;
    final ready = Completer<void>();
    _socketSubscription = socket.messages.listen(
      (message) => _handleServerMessage(sessionId, message, ready),
      onDone: () => _handleSocketClosed(sessionId, ready),
      onError: (Object error) => _handleSocketError(sessionId, ready, error),
      cancelOnError: true,
    );
    socket.add(jsonEncode(<String, Object>{
      'type': 'hello',
      'version': 1,
      'sampleRate': streamingSampleRate,
      'channels': streamingChannels,
      'format': 'pcm_s16le',
      'token': target.token,
      'device': Platform.operatingSystem,
    }));
    await ready.future.timeout(
      const Duration(seconds: 5),
      onTimeout: () => throw const BridgeException('Windows 未确认连接'),
    );
  }

  Future<void> _ensurePermissions() async {
    if (!await _audioCapture.hasPermission()) {
      throw const BridgeException('未获得麦克风权限');
    }
    if (!await _platformAudioResources.prepare()) {
      throw const BridgeException('未获得通知权限，无法显示后台录音通知');
    }
  }

  Future<bool> _startAudioCapture(int sessionId, String targetLabel) async {
    if (_audioSubscription != null || await _audioCapture.isRecording()) {
      throw const BridgeException('录音资源仍在使用，请先停止后重试');
    }
    final start = _audioCapture.startStream(targetLabel);
    _pendingRecorderStart = start.then<void>((_) {});
    late final Stream<List<int>> audioStream;
    try {
      audioStream = await start;
    } finally {
      _pendingRecorderStart = null;
    }
    if (!_isCurrent(sessionId)) {
      await _stopCapture();
      return false;
    }
    _audioSubscription = audioStream.listen(
      (chunk) {
        if (!_isCurrent(sessionId) || _userPauseRequested) return;
        final socket = _socket;
        if (socket?.isOpen == true) {
          socket!.add(
            _state.gain == 1 ? chunk : applyPcm16Gain(chunk, _state.gain),
          );
        }
      },
      onError: (Object error) {
        if (_isCurrent(sessionId)) _captureFailed('录音失败：$error');
      },
      cancelOnError: true,
    );
    return true;
  }

  void _handleServerMessage(
    int sessionId,
    dynamic message,
    Completer<void> ready,
  ) {
    if (!_isCurrent(sessionId) || message is! String) return;
    try {
      final decoded = jsonDecode(message);
      if (decoded is! Map<String, dynamic>) return;
      if (decoded['type'] == 'ready' && !ready.isCompleted) {
        ready.complete();
      } else if (decoded['type'] == 'error') {
        final serverMessage = decoded['message']?.toString() ?? 'Windows 拒绝连接';
        if (!ready.isCompleted) {
          ready.completeError(BridgeException(serverMessage));
        } else {
          unawaited(_serialize(() => _failAndCleanup(serverMessage, sessionId)));
        }
      }
    } on FormatException {
      return;
    }
  }

  void _handleSocketClosed(int sessionId, Completer<void> ready) {
    if (!_isCurrent(sessionId)) return;
    _socket = null;
    if (!ready.isCompleted) {
      ready.completeError(const BridgeException('Windows 已断开连接'));
    } else if (_state.bridgeState == BridgeState.paused) {
      _emit(_state.copyWith(status: '连接已断开，继续时将重新连接'));
    } else {
      unawaited(_serialize(() => _failAndCleanup('Windows 已断开连接', sessionId)));
    }
  }

  void _handleSocketError(
    int sessionId,
    Completer<void> ready,
    Object error,
  ) {
    if (!_isCurrent(sessionId)) return;
    _socket = null;
    final message = _safeError('网络错误', error);
    if (!ready.isCompleted) {
      ready.completeError(BridgeException(message));
    } else if (_state.bridgeState == BridgeState.paused) {
      _emit(_state.copyWith(status: '网络已断开，继续时将重新连接'));
    } else {
      unawaited(_serialize(() => _failAndCleanup(message, sessionId)));
    }
  }

  void _handleCaptureState(CaptureState captureState) {
    if (_disposed || _cleanupInProgress || _userPauseRequested ||
        _state.bridgeState != BridgeState.streaming) {
      return;
    }
    switch (captureState) {
      case CaptureState.recording:
        if (_state.interruptionState == InterruptionState.interrupted) {
          _markInterruptionEnded();
        }
        break;
      case CaptureState.paused:
        _markInterrupted();
        break;
      case CaptureState.stopped:
        _captureFailed('系统已停止麦克风录音，请检查权限或音频设备');
        break;
    }
  }

  void _markInterrupted() {
    if (_state.bridgeState != BridgeState.streaming || _userPauseRequested) return;
    _finishDurationTracking();
    _emit(_state.copyWith(
      interruptionState: InterruptionState.interrupted,
      status: '录音被系统暂时中断',
    ));
  }

  void _markInterruptionEnded() {
    if (_state.bridgeState != BridgeState.streaming || _userPauseRequested) return;
    _beginDurationTracking();
    _emit(_state.copyWith(
      interruptionState: InterruptionState.none,
      status: '麦克风正在传输',
    ));
  }

  Future<void> _resumeAfterInterruption() async {
    if (_state.bridgeState != BridgeState.streaming || _userPauseRequested) return;
    final sessionId = _sessionId;
    try {
      await _audioCapture.resumeAfterInterruption();
      if (_isCurrent(sessionId) && !_userPauseRequested) {
        _markInterruptionEnded();
      }
    } catch (error) {
      await _failAndCleanup(
        _safeError('系统中断后无法继续录音', error),
        sessionId,
      );
    }
  }

  void _captureFailed(String message) {
    if (_disposed || _state.bridgeState != BridgeState.streaming) return;
    final sessionId = _sessionId;
    unawaited(_serialize(() => _failAndCleanup(message, sessionId)));
  }

  Future<void> _validateForegroundSession() async {
    if (_state.bridgeState == BridgeState.streaming) {
      if (_socket?.isOpen != true) {
        await _failAndCleanup('后台录音或网络连接已终止，请重新开始', _sessionId);
      } else if (_state.interruptionState == InterruptionState.interrupted) {
        _emit(_state.copyWith(status: '录音仍被系统中断'));
      } else if (!await _audioCapture.isRecording()) {
        await _failAndCleanup('后台录音已终止，请重新开始', _sessionId);
      } else {
        _refreshDuration();
      }
    } else if (_state.bridgeState == BridgeState.paused) {
      _emit(_state.copyWith(
        status: _socket?.isOpen == true
            ? '麦克风已暂停'
            : '连接已断开，继续时将重新连接',
      ));
    }
  }

  Future<void> _cancelIncompleteStartup() async {
    if (_state.bridgeState == BridgeState.connecting ||
        _state.bridgeState == BridgeState.resuming) {
      await _stop(emitIdle: true, status: '已取消后台启动');
    }
  }

  Future<void> _failAndCleanup(String message, int sessionId) async {
    if (!_isCurrent(sessionId)) return;
    _setError(message);
    await _stop(emitIdle: false);
  }

  Future<void> _stop({required bool emitIdle, String status = '已停止'}) async {
    final stoppedSession = _sessionId;
    _sessionId++;
    _cleanupInProgress = true;
    try {
      _finishDurationTracking();
      await _pendingRecorderStart;
      await _stopCapture();
      await _closeSocket();
      await _stopPlatformAudio();
      await _disableWakelock();
      _target = null;
      _userPauseRequested = false;
      if (emitIdle && !_disposed && _sessionId == stoppedSession + 1) {
        _capturedDuration = Duration.zero;
        _emit(_state.copyWith(
          bridgeState: BridgeState.idle,
          status: status,
          duration: Duration.zero,
          userPaused: false,
          interruptionState: InterruptionState.none,
        ));
      }
    } finally {
      _cleanupInProgress = false;
    }
  }

  void _ensureCaptureStateSubscription() {
    _captureStateSubscription ??= _audioCapture.stateChanges.listen(
      _handleCaptureState,
      onError: (Object error) => _captureFailed('录音失败：$error'),
    );
  }

  void _ensurePlatformEventSubscription() {
    _platformEventSubscription ??=
        _platformAudioResources.events.listen(handlePlatformAudioEvent);
  }

  Future<void> _stopCapture() async {
    try {
      await _audioSubscription?.cancel();
    } catch (_) {}
    _audioSubscription = null;
    try {
      if (await _audioCapture.isRecording()) await _audioCapture.stop();
    } catch (_) {}
  }

  Future<void> _closeSocket() async {
    final subscription = _socketSubscription;
    _socketSubscription = null;
    try {
      await subscription?.cancel();
    } catch (_) {}
    final socket = _socket;
    _socket = null;
    try {
      await socket?.close();
    } catch (_) {}
  }

  Future<void> _enableWakelock(int sessionId) async {
    await _wakelock.enable();
    if (!_isCurrent(sessionId)) {
      await _wakelock.disable();
      return;
    }
    _wakelockEnabled = true;
  }

  Future<void> _startPlatformAudio(int sessionId, String targetLabel) async {
    await _platformAudioResources.start(targetLabel);
    if (!_isCurrent(sessionId)) {
      await _platformAudioResources.stop();
      return;
    }
    _platformAudioStarted = true;
  }

  Future<void> _stopPlatformAudio() async {
    if (!_platformAudioStarted) return;
    _platformAudioStarted = false;
    try {
      await _platformAudioResources.stop();
    } catch (_) {}
  }

  Future<void> _disableWakelock() async {
    if (!_wakelockEnabled) return;
    _wakelockEnabled = false;
    try {
      await _wakelock.disable();
    } catch (_) {}
  }

  void _sendControl(String type) {
    final socket = _socket;
    if (socket?.isOpen == true) {
      socket!.add(jsonEncode(<String, Object>{'type': type}));
    }
  }

  void _beginDurationTracking() {
    if (_captureStartedAt != null) return;
    _captureStartedAt = DateTime.now();
    _durationTimer?.cancel();
    _durationTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => _refreshDuration(),
    );
  }

  void _finishDurationTracking() {
    final startedAt = _captureStartedAt;
    if (startedAt != null) {
      _capturedDuration += DateTime.now().difference(startedAt);
      _captureStartedAt = null;
    }
    _durationTimer?.cancel();
    _durationTimer = null;
    _emit(_state.copyWith(duration: _capturedDuration));
  }

  void _refreshDuration() {
    final startedAt = _captureStartedAt;
    final duration = startedAt == null
        ? _capturedDuration
        : _capturedDuration + DateTime.now().difference(startedAt);
    _emit(_state.copyWith(duration: duration));
  }

  Future<void> _serialize(Future<void> Function() operation) {
    final result = _controlTail.then((_) => operation());
    _controlTail = result.catchError((Object _) {});
    return result;
  }

  bool _isCurrent(int sessionId) => !_disposed && sessionId == _sessionId;

  String _safeError(String prefix, Object error) {
    final detail = error is BridgeException ? error.message : error.toString();
    final token = _target?.token ?? '';
    final safeDetail = token.isEmpty ? detail : detail.replaceAll(token, '[已隐藏]');
    return '$prefix：$safeDetail';
  }

  void _setError(String message) {
    _emit(_state.copyWith(bridgeState: BridgeState.error, status: message));
  }

  void _emit(StreamingSessionState nextState) {
    if (_disposed) return;
    _state = nextState;
    notifyListeners();
  }

  Future<void> shutdown() async {
    if (_disposed) return;
    await _serialize(() => _stop(emitIdle: false));
    await _captureStateSubscription?.cancel();
    await _platformEventSubscription?.cancel();
    try {
      await _audioCapture.dispose();
    } catch (_) {}
    try {
      await _platformAudioResources.dispose();
    } catch (_) {}
    _disposed = true;
    super.dispose();
  }
}

class RecordAudioCapture implements AudioCapture {
  RecordAudioCapture() : _recorder = AudioRecorder() {
    _stateChanges = _recorder.onStateChanged().map(
          (state) => switch (state) {
            RecordState.record => CaptureState.recording,
            RecordState.pause => CaptureState.paused,
            RecordState.stop => CaptureState.stopped,
          },
        );
  }

  final AudioRecorder _recorder;
  late final Stream<CaptureState> _stateChanges;

  @override
  Stream<CaptureState> get stateChanges => _stateChanges;

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<bool> isRecording() => _recorder.isRecording();

  @override
  Future<Stream<List<int>>> startStream(String targetLabel) {
    return _recorder.startStream(RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: streamingSampleRate,
      numChannels: streamingChannels,
      autoGain: false,
      echoCancel: false,
      noiseSuppress: false,
      audioInterruption: Platform.isIOS
          ? AudioInterruptionMode.pause
          : AudioInterruptionMode.pauseResume,
      iosConfig: const IosRecordConfig(
        categoryOptions: [IosAudioCategoryOption.allowBluetooth],
      ),
    ));
  }

  @override
  Future<void> stop() async {
    await _recorder.stop();
    await _recorder.ios?.setAudioSessionActive(false);
  }

  @override
  Future<void> resumeAfterInterruption() => _recorder.resume();

  @override
  Future<void> dispose() => _recorder.dispose();
}

class IoStreamingSocketFactory implements StreamingSocketFactory {
  @override
  Future<StreamingSocket> connect(Uri uri) async {
    // Accept the receiver's self-signed LAN certificate for wss://.
    final socket = await WebSocket.connect(
      uri.toString(),
      customClient: uri.scheme == 'wss'
          ? (HttpClient()
            ..badCertificateCallback =
                (X509Certificate cert, String host, int port) => true)
          : null,
    );
    socket.pingInterval = const Duration(seconds: 10);
    return IoStreamingSocket(socket);
  }
}

class IoStreamingSocket implements StreamingSocket {
  IoStreamingSocket(this._socket);
  final WebSocket _socket;
  @override
  bool get isOpen => _socket.readyState == WebSocket.open;
  @override
  Stream<dynamic> get messages => _socket;
  @override
  void add(Object data) => _socket.add(data);
  @override
  Future<void> close() async {
    await _socket.close(WebSocketStatus.normalClosure, 'stopped');
  }
}

class WakelockSession implements SessionWakelock {
  @override
  Future<void> enable() => WakelockPlus.enable();
  @override
  Future<void> disable() => WakelockPlus.disable();
}
