import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:record/record.dart';

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

enum BridgeState { idle, connecting, streaming, error }

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

  WebSocket? _socket;
  StreamSubscription<List<int>>? _audioSubscription;
  Timer? _durationTimer;
  BridgeState _bridgeState = BridgeState.idle;
  Duration _duration = Duration.zero;
  String _status = '输入 Windows 电脑的局域网 IP';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      unawaited(_stopStreaming());
    }
  }

  Future<void> _startStreaming() async {
    FocusManager.instance.primaryFocus?.unfocus();
    final host = _hostController.text.trim();
    final port = int.tryParse(_portController.text.trim());
    if (host.isEmpty || port == null || port < 1 || port > 65535) {
      _setError('IP 地址或端口无效');
      return;
    }

    setState(() {
      _bridgeState = BridgeState.connecting;
      _status = '正在连接 Windows…';
    });

    try {
      if (!await _recorder.hasPermission()) {
        _setError('未获得麦克风权限');
        return;
      }

      final socket = await WebSocket.connect('ws://$host:$port/mic')
          .timeout(const Duration(seconds: 8));
      socket.pingInterval = const Duration(seconds: 10);
      _socket = socket;
      socket.add(jsonEncode(<String, Object>{
        'type': 'hello',
        'version': 1,
        'sampleRate': sampleRate,
        'channels': channels,
        'format': 'pcm_s16le',
        'token': _tokenController.text,
        'device': Platform.operatingSystem,
      }));

      final audioStream = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: sampleRate,
          numChannels: channels,
          autoGain: false,
          echoCancel: false,
          noiseSuppress: false,
        ),
      );
      _audioSubscription = audioStream.listen(
        (chunk) {
          final activeSocket = _socket;
          if (activeSocket?.readyState == WebSocket.open) {
            activeSocket!.add(chunk);
          }
        },
        onError: (Object error) {
          _setError('录音失败：$error');
          unawaited(_stopStreaming(keepError: true));
        },
        cancelOnError: true,
      );

      socket.listen(
        _handleServerMessage,
        onDone: () {
          if (_bridgeState == BridgeState.streaming) {
            _setError('Windows 已断开连接');
          }
          unawaited(_stopStreaming(keepError: true));
        },
        onError: (Object error) {
          _setError('网络错误：$error');
          unawaited(_stopStreaming(keepError: true));
        },
        cancelOnError: true,
      );

      _duration = Duration.zero;
      _durationTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) {
          setState(() => _duration += const Duration(seconds: 1));
        }
      });
      setState(() {
        _bridgeState = BridgeState.streaming;
        _status = '麦克风正在传输';
      });
    } on TimeoutException {
      _setError('连接超时，请检查 IP、防火墙和端口');
      await _stopStreaming(keepError: true);
    } catch (error) {
      _setError('连接失败：$error');
      await _stopStreaming(keepError: true);
    }
  }

  void _handleServerMessage(dynamic message) {
    if (message is! String) return;
    try {
      final payload = jsonDecode(message) as Map<String, dynamic>;
      if (payload['type'] == 'error') {
        _setError(payload['message']?.toString() ?? 'Windows 拒绝连接');
        unawaited(_stopStreaming(keepError: true));
      }
    } on FormatException {
      return;
    }
  }

  Future<void> _stopStreaming({bool keepError = false}) async {
    _durationTimer?.cancel();
    _durationTimer = null;
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    if (await _recorder.isRecording()) await _recorder.stop();

    final socket = _socket;
    _socket = null;
    await socket?.close(WebSocketStatus.normalClosure, 'stopped');

    if (mounted && !(keepError && _bridgeState == BridgeState.error)) {
      setState(() {
        _bridgeState = BridgeState.idle;
        _status = '已停止';
        _duration = Duration.zero;
      });
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
    WidgetsBinding.instance.removeObserver(this);
    _durationTimer?.cancel();
    _audioSubscription?.cancel();
    _socket?.close();
    _recorder.dispose();
    _hostController.dispose();
    _portController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isBusy = _bridgeState == BridgeState.connecting ||
        _bridgeState == BridgeState.streaming;
    final isStreaming = _bridgeState == BridgeState.streaming;

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
                  if (isStreaming) ...[
                    const SizedBox(height: 8),
                    Text(
                      _formattedDuration,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ],
                  const SizedBox(height: 32),
                  TextField(
                    controller: _hostController,
                    enabled: !isBusy,
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
                    enabled: !isBusy,
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
                    enabled: !isBusy,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: '连接密码（可选）',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.lock_outline_rounded),
                    ),
                  ),
                  const SizedBox(height: 24),
                  FilledButton.icon(
                    onPressed: _bridgeState == BridgeState.connecting
                        ? null
                        : isStreaming
                            ? _stopStreaming
                            : _startStreaming,
                    icon: Icon(isStreaming ? Icons.stop : Icons.mic),
                    label: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      child: Text(isStreaming ? '停止传输' : '开始传输'),
                    ),
                  ),
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
