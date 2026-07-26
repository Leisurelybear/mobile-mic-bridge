import 'dart:async';

import 'package:flutter/material.dart';

import 'connection_preferences.dart';
import 'qr_scanner_page.dart';
import 'receiver_discovery.dart';
import 'streaming/streaming_session_controller.dart';
import 'streaming/streaming_session_state.dart';

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

class MicBridgePage extends StatefulWidget {
  const MicBridgePage({super.key});

  @override
  State<MicBridgePage> createState() => _MicBridgePageState();
}

class _MicBridgePageState extends State<MicBridgePage>
    with WidgetsBindingObserver {
  final TextEditingController _hostController =
      TextEditingController(text: '192.168.1.100');
  final TextEditingController _portController =
      TextEditingController(text: '8765');
  final TextEditingController _tokenController = TextEditingController();
  final ConnectionPreferences _connectionPreferences = ConnectionPreferences();
  final ReceiverDiscovery _receiverDiscovery = ReceiverDiscovery();
  final StreamingSessionController _streamingController =
      StreamingSessionController();

  BridgeState get _bridgeState => _streamingController.state.bridgeState;
  Duration get _duration => _streamingController.state.duration;
  double get _gain => _streamingController.state.gain;
  String get _status => _streamingController.state.status;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _streamingController.addListener(_handleStreamingChanged);
    _receiverDiscovery.addListener(_handleDiscoveryChanged);
    unawaited(_loadSavedConnection());
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_receiverDiscovery.start());
    });
  }

  void _handleStreamingChanged() {
    if (mounted) setState(() {});
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
    _streamingController.setGain((saved.gain ?? 1).clamp(0, 2).toDouble());
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
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('二维码配对信息已填写')),
    );
    await _saveConnectionPreferences();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _streamingController.handleLifecycleState(state);
  }

  Future<void> _startStreaming() async {
    FocusManager.instance.primaryFocus?.unfocus();
    final host = _hostController.text.trim();
    final port = int.tryParse(_portController.text.trim());
    if (host.isEmpty || port == null || port < 1 || port > 65535) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('IP 地址或端口无效')),
      );
      return;
    }
    await _saveConnectionPreferences();
    await _streamingController.start(StreamingTarget(
      host: host,
      port: port,
      token: _tokenController.text,
    ));
  }

  Future<void> _pauseStreaming() => _streamingController.pause();

  void _selectReceiver(DiscoveredReceiver receiver) {
    if (_bridgeState != BridgeState.idle &&
        _bridgeState != BridgeState.error) {
      return;
    }
    _hostController.text = receiver.host;
    _portController.text = receiver.port.toString();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('已选择 ${receiver.name}')),
    );
    unawaited(_saveConnectionPreferences());
  }

  Future<void> _resumeStreaming() => _streamingController.resume();

  Future<void> _stopStreaming() => _streamingController.stop();

  String get _formattedDuration {
    final minutes = _duration.inMinutes.toString().padLeft(2, '0');
    final seconds = (_duration.inSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _streamingController.removeListener(_handleStreamingChanged);
    _receiverDiscovery.removeListener(_handleDiscoveryChanged);
    _receiverDiscovery.dispose();
    unawaited(_streamingController.shutdown());
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
      primaryAction = _pauseStreaming;
      primaryIcon = Icons.pause;
      primaryLabel = '暂停';
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
                    onChanged: _streamingController.setGain,
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
