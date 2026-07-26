import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import 'audio_gain.dart';
import 'connection_preferences.dart';
import 'qr_scanner_page.dart';
import 'receiver_discovery.dart';

void main() => runApp(const MobileMicApp());

class MobileMicApp extends StatelessWidget {
  const MobileMicApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Mobile Mic Bridge',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff3b82f6),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const MicBridgePage(),
    );
  }
}

enum BridgeState { idle, connecting, streaming, paused, resuming, error }

class BridgeException implements Exception {
  const BridgeException(this.message);

  final String message;

  @override
  String toString() => message;
}

class MicBridgePage extends StatefulWidget {
  const MicBridgePage({super.key});

  @override
  State<MicBridgePage> createState() => _MicBridgePageState();
}

class _MicBridgePageState extends State<MicBridgePage>
    with WidgetsBindingObserver {
  static const sampleRate = 48000;
  static const channels = 1;

  final AudioRecorder _recorder = AudioRecorder();
  final TextEditingController _hostController =
      TextEditingController(text: '192.168.1.100');
  final TextEditingController _portController =
      TextEditingController(text: '8765');
  final TextEditingController _tokenController = TextEditingController();
  final ConnectionPreferences _connectionPreferences = ConnectionPreferences();
  final ReceiverDiscovery _receiverDiscovery = ReceiverDiscovery();

  WebSocket? _socket;
  StreamSubscription<List<int>>? _audioSubscription;
  Future<void>? _pendingRecorderStart;
  Timer? _durationTimer;
  int _sessionId = 0;
  int? _wakelockSessionId;
  bool _isStopping = false;
  bool _isPausing = false;
  double _gain = 1;
  BridgeState _bridgeState = BridgeState.idle;
  Duration _duration = Duration.zero;
  String _status = '输入 Windows 电脑的局域网 IP';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _receiverDiscovery.addListener(_handleDiscoveryChanged);
    unawaited(_loadSavedConnection());
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_receiverDiscovery.start());
    });
  }

  void _handleDiscoveryChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _loadSavedConnection() async {
    late final SavedConnection saved;
    try {
      saved = await _connectionPreferences.load();
    } catch (_) {
      return;
    }
    if (!mounted) return;
    if (saved.host?.isNotEmpty ?? false) {
      _hostController.text = saved.host!;
    }
    if (saved.port != null) {
      _portController.text = saved.port.toString();
    }
    setState(() {
      _gain = (saved.gain ?? 1).clamp(0, 2).toDouble();
    });
  }

  Future<void> _saveConnectionPreferences() async {
    final host = _hostController.text.trim();
    final port = int.tryParse(_portController.text.trim());
    if (host.isEmpty || port == null) return;
    try {
      await _connectionPreferences.save(
        host: host,
        port: port,
        gain: _gain,
      );
    } catch (_) {}
  }

  Future<void> _scanPairingQr() async {
    final payload = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const QrScannerPage()),
    );
    if (!mounted || payload == null) return;
    final uri = Uri.tryParse(payload);
    final host = uri?.queryParameters['host'];
    final port = int.tryParse(uri?.queryParameters['port'] ?? '');
    if (uri?.scheme != 'mobilemic' ||
        uri?.host != 'connect' ||
        host == null ||
        host.isEmpty ||
        port == null ||
        port < 1 ||
        port > 65535) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('二维码不是有效的 Mobile Mic 配对码')),
      );
      return;
    }
    _hostController.text = host;
    _portController.text = port.toString();
    final token = uri?.queryParameters['token'];
    if (token != null) _tokenController.text = token;
    setState(() => _status = '二维码配对信息已填写');
    await _saveConnectionPreferences();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      unawaited(_stopStreaming());
    }
  }

  Future<void> _startStreaming() async {
    if (_isStopping) return;
    FocusManager.instance.primaryFocus?.unfocus();
    final host = _hostController.text.trim();
    final port = int.tryParse(_portController.text.trim());
    if (host.isEmpty || port == null || port < 1 || port > 65535) {
      _setError('IP 地址或端口无效');
      return;
    }
    await _saveConnectionPreferences();

    final sessionId = ++_sessionId;
    setState(() {
      _bridgeState = BridgeState.connecting;
      _status = '正在连接 Windows…';
    });

    try {
      if (!await _recorder.hasPermission()) {
        _setError('未获得麦克风权限');
        return;
      }

      final socketHost = host.contains(':') && !host.startsWith('[')
          ? '[$host]'
          : host;
      final socket = await WebSocket.connect('ws://$socketHost:$port/mic')
          .timeout(const Duration(seconds: 8));
      if (sessionId != _sessionId) {
        await socket.close();
        return;
      }
      socket.pingInterval = const Duration(seconds: 10);
      _socket = socket;
      final ready = Completer<void>();
      socket.listen(
        (message) => _handleServerMessage(sessionId, message, ready),
        onDone: () => _handleSocketClosed(sessionId, ready),
        onError: (Object error) =>
            _handleSocketError(sessionId, ready, error),
        cancelOnError: true,
      );
      socket.add(jsonEncode(<String, Object>{
        'type': 'hello',
        'version': 1,
        'sampleRate': sampleRate,
        'channels': channels,
        'format': 'pcm_s16le',
        'token': _tokenController.text,
        'device': Platform.operatingSystem,
      }));
      await ready.future.timeout(
        const Duration(seconds: 5),
        onTimeout: () => throw const BridgeException('Windows 未确认连接'),
      );
      if (sessionId != _sessionId) return;

      if (!await _startAudioCapture(sessionId)) return;
      _wakelockSessionId = sessionId;
      await WakelockPlus.enable();
      if (sessionId != _sessionId) {
        if (_wakelockSessionId == sessionId) {
          _wakelockSessionId = null;
          await WakelockPlus.disable();
        }
        return;
      }

      _duration = Duration.zero;
      _startDurationTimer();
      setState(() {
        _bridgeState = BridgeState.streaming;
        _status = '麦克风正在传输';
      });
    } on TimeoutException {
      if (sessionId != _sessionId) return;
      _setError('连接超时，请检查 IP、防火墙和端口');
      await _stopStreaming(sessionId: sessionId, keepError: true);
    } catch (error) {
      if (sessionId != _sessionId) return;
      _setError('连接失败：$error');
      await _stopStreaming(sessionId: sessionId, keepError: true);
    }
  }

  Future<bool> _startAudioCapture(int sessionId) async {
    final recorderStartCompleted = Completer<void>();
    final pendingStart = recorderStartCompleted.future;
    _pendingRecorderStart = pendingStart;
    late final Stream<List<int>> audioStream;
    try {
      audioStream = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: sampleRate,
          numChannels: channels,
          autoGain: false,
          echoCancel: false,
          noiseSuppress: false,
        ),
      );
    } finally {
      recorderStartCompleted.complete();
      if (identical(_pendingRecorderStart, pendingStart)) {
        _pendingRecorderStart = null;
      }
    }
    if (sessionId != _sessionId) return false;
    _audioSubscription = audioStream.listen(
      (chunk) {
        final activeSocket = _socket;
        if (activeSocket?.readyState == WebSocket.open) {
          activeSocket!.add(
            _gain == 1 ? chunk : applyPcm16Gain(chunk, _gain),
          );
        }
      },
      onError: (Object error) {
        if (sessionId != _sessionId) return;
        _setError('录音失败：$error');
        unawaited(
          _stopStreaming(sessionId: sessionId, keepError: true),
        );
      },
      cancelOnError: true,
    );
    return sessionId == _sessionId;
  }

  void _startDurationTimer() {
    _durationTimer?.cancel();
    _durationTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _bridgeState == BridgeState.streaming) {
        setState(() => _duration += const Duration(seconds: 1));
      }
    });
  }

  Future<void> _pauseStreaming() async {
    if (_bridgeState != BridgeState.streaming || _isPausing) return;
    _isPausing = true;
    final sessionId = _sessionId;
    setState(() => _status = '正在暂停录音…');
    try {
      _durationTimer?.cancel();
      _durationTimer = null;
      await _audioSubscription?.cancel();
      _audioSubscription = null;
      if (await _recorder.isRecording()) await _recorder.stop();
      if (sessionId != _sessionId) return;
      _sendControl('pause');
      setState(() {
        _bridgeState = BridgeState.paused;
        _status = '麦克风已暂停';
      });
    } catch (error) {
      if (sessionId != _sessionId) return;
      _setError('暂停失败：$error');
      await _stopStreaming(sessionId: sessionId, keepError: true);
    } finally {
      _isPausing = false;
    }
  }

  void _selectReceiver(DiscoveredReceiver receiver) {
    if (_bridgeState != BridgeState.idle &&
        _bridgeState != BridgeState.error) {
      return;
    }
    _hostController.text = receiver.host;
    _portController.text = receiver.port.toString();
    setState(() => _status = '已选择 ${receiver.name}');
    unawaited(_saveConnectionPreferences());
  }

  Future<void> _resumeStreaming() async {
    if (_bridgeState != BridgeState.paused || _isStopping) return;
    final sessionId = _sessionId;
    setState(() {
      _bridgeState = BridgeState.resuming;
      _status = '正在继续录音…';
    });
    try {
      if (_socket?.readyState != WebSocket.open) {
        throw const BridgeException('Windows 连接已经断开');
      }
      _sendControl('resume');
      if (!await _startAudioCapture(sessionId)) return;
      _startDurationTimer();
      setState(() {
        _bridgeState = BridgeState.streaming;
        _status = '麦克风正在传输';
      });
    } catch (error) {
      if (sessionId != _sessionId) return;
      _setError('继续失败：$error');
      await _stopStreaming(sessionId: sessionId, keepError: true);
    }
  }

  void _sendControl(String type) {
    final socket = _socket;
    if (socket?.readyState == WebSocket.open) {
      socket!.add(jsonEncode(<String, Object>{'type': type}));
    }
  }

  void _handleServerMessage(
    int sessionId,
    dynamic message,
    Completer<void> ready,
  ) {
    if (sessionId != _sessionId || message is! String) return;
    try {
      final decoded = jsonDecode(message);
      if (decoded is! Map<String, dynamic>) return;
      final payload = decoded;
      if (payload['type'] == 'ready' && !ready.isCompleted) {
        ready.complete();
        return;
      }
      if (payload['type'] == 'error') {
        final message = payload['message']?.toString() ?? 'Windows 拒绝连接';
        if (!ready.isCompleted) {
          ready.completeError(BridgeException(message));
        } else {
          _setError(message);
          unawaited(
            _stopStreaming(sessionId: sessionId, keepError: true),
          );
        }
      }
    } on FormatException {
      return;
    }
  }

  void _handleSocketClosed(int sessionId, Completer<void> ready) {
    if (sessionId != _sessionId) return;
    const message = 'Windows 已断开连接';
    if (!ready.isCompleted) {
      ready.completeError(const BridgeException(message));
      return;
    }
    _setError(message);
    unawaited(_stopStreaming(sessionId: sessionId, keepError: true));
  }

  void _handleSocketError(
    int sessionId,
    Completer<void> ready,
    Object error,
  ) {
    if (sessionId != _sessionId) return;
    final message = '网络错误：$error';
    if (!ready.isCompleted) {
      ready.completeError(BridgeException(message));
      return;
    }
    _setError(message);
    unawaited(_stopStreaming(sessionId: sessionId, keepError: true));
  }

  Future<void> _stopStreaming({
    int? sessionId,
    bool keepError = false,
  }) async {
    if (_isStopping || (sessionId != null && sessionId != _sessionId)) return;
    _isStopping = true;
    final stoppedSession = _sessionId;
    _sessionId++;
    try {
      _durationTimer?.cancel();
      _durationTimer = null;
      await _pendingRecorderStart;
      try {
        await _audioSubscription?.cancel();
      } catch (_) {}
      _audioSubscription = null;
      try {
        if (await _recorder.isRecording()) await _recorder.stop();
      } catch (_) {}
      if (_wakelockSessionId == stoppedSession) {
        _wakelockSessionId = null;
        try {
          await WakelockPlus.disable();
        } catch (_) {}
      }

      final socket = _socket;
      _socket = null;
      try {
        await socket?.close(WebSocketStatus.normalClosure, 'stopped');
      } catch (_) {}

      if (mounted &&
          _sessionId == stoppedSession + 1 &&
          !(keepError && _bridgeState == BridgeState.error)) {
        setState(() {
          _bridgeState = BridgeState.idle;
          _status = '已停止';
          _duration = Duration.zero;
        });
      }
    } finally {
      _isStopping = false;
    }
  }

  void _setError(String message) {
    if (!mounted) return;
    setState(() {
      _bridgeState = BridgeState.error;
      _status = message;
    });
  }

  String get _formattedDuration {
    final minutes = _duration.inMinutes.toString().padLeft(2, '0');
    final seconds = (_duration.inSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  @override
  void dispose() {
    _sessionId++;
    _wakelockSessionId = null;
    WidgetsBinding.instance.removeObserver(this);
    _receiverDiscovery.removeListener(_handleDiscoveryChanged);
    _receiverDiscovery.dispose();
    _durationTimer?.cancel();
    _audioSubscription?.cancel();
    _socket?.close();
    unawaited(WakelockPlus.disable());
    _recorder.dispose();
    _hostController.dispose();
    _portController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settingsLocked = _bridgeState != BridgeState.idle &&
        _bridgeState != BridgeState.error;
    final isStreaming = _bridgeState == BridgeState.streaming;
    final isPaused = _bridgeState == BridgeState.paused;
    final isConnected = isStreaming ||
        isPaused ||
        _bridgeState == BridgeState.resuming;
    final showDuration = isConnected;
    VoidCallback? primaryAction;
    var primaryIcon = Icons.mic;
    var primaryLabel = '开始传输';
    if (isStreaming) {
      primaryAction = _isPausing ? null : _pauseStreaming;
      primaryIcon = Icons.pause;
      primaryLabel = _isPausing ? '正在暂停…' : '暂停';
    } else if (isPaused) {
      primaryAction = _resumeStreaming;
      primaryIcon = Icons.play_arrow;
      primaryLabel = '继续';
    } else if (_bridgeState == BridgeState.connecting ||
        _bridgeState == BridgeState.resuming) {
      primaryAction = null;
      primaryIcon = Icons.hourglass_top;
      primaryLabel = _bridgeState == BridgeState.connecting
          ? '正在连接…'
          : '正在继续…';
    } else {
      primaryAction = _startStreaming;
    }

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.mic_rounded, size: 72),
                  const SizedBox(height: 12),
                  Text(
                    'Mobile Mic Bridge',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _status,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: _bridgeState == BridgeState.error
                          ? Theme.of(context).colorScheme.error
                          : null,
                    ),
                  ),
                  if (showDuration) ...[
                    const SizedBox(height: 8),
                    Text(
                      _formattedDuration,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ],
                  const SizedBox(height: 24),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.radar),
                              const SizedBox(width: 10),
                              const Expanded(
                                child: Text(
                                  '自动发现 Windows',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                              ),
                              IconButton(
                                onPressed: settingsLocked ? null : _scanPairingQr,
                                tooltip: '扫描配对二维码',
                                icon: const Icon(Icons.qr_code_scanner),
                              ),
                              IconButton(
                                onPressed: _receiverDiscovery.refresh,
                                tooltip: '重新扫描',
                                icon: const Icon(Icons.refresh),
                              ),
                            ],
                          ),
                          Text(_receiverDiscovery.status),
                          for (final receiver
                              in _receiverDiscovery.receivers.take(5))
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              leading: const Icon(Icons.computer),
                              title: Text(receiver.name),
                              subtitle: Text(
                                '${receiver.host}:${receiver.port}',
                              ),
                              trailing: const Icon(Icons.chevron_right),
                              onTap: settingsLocked
                                  ? null
                                  : () => _selectReceiver(receiver),
                            ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _hostController,
                    enabled: !settingsLocked,
                    keyboardType: TextInputType.url,
                    decoration: const InputDecoration(
                      labelText: 'Windows IP 地址',
                      hintText: '例如 192.168.1.100',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.computer_rounded),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: _portController,
                    enabled: !settingsLocked,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '端口',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.lan_rounded),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: _tokenController,
                    enabled: !settingsLocked,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: '连接密码（可选）',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.lock_outline_rounded),
                    ),
                  ),
                  const SizedBox(height: 18),
                  Row(
                    children: [
                      const Icon(Icons.volume_up),
                      const SizedBox(width: 10),
                      const Expanded(child: Text('发送音量')),
                      Text('${(_gain * 100).round()}%'),
                    ],
                  ),
                  Slider(
                    value: _gain,
                    min: 0,
                    max: 2,
                    divisions: 40,
                    label: '${(_gain * 100).round()}%',
                    onChanged: (value) => setState(() => _gain = value),
                    onChangeEnd: (_) => unawaited(
                      _saveConnectionPreferences(),
                    ),
                  ),
                  const Text(
                    '100% 为原始音量；超过 100% 可能产生削波失真。',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    '应用会记住 IP、端口和音量；连接密码不会保存。',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: primaryAction,
                    icon: Icon(primaryIcon),
                    label: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      child: Text(primaryLabel),
                    ),
                  ),
                  if (isConnected) ...[
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: _stopStreaming,
                      icon: const Icon(Icons.stop),
                      label: const Padding(
                        padding: EdgeInsets.symmetric(vertical: 12),
                        child: Text('断开连接'),
                      ),
                    ),
                  ],
                  const SizedBox(height: 20),
                  const Text(
                    '手机和电脑需要连接同一个 Wi-Fi。建议佩戴耳机，避免电脑扬声器声音被手机再次收录。',
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
