import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_mic_bridge/streaming/platform_audio_events.dart';
import 'package:mobile_mic_bridge/streaming/streaming_session_controller.dart';
import 'package:mobile_mic_bridge/streaming/streaming_session_state.dart';

void main() {
  const target = StreamingTarget(host: '192.168.1.2', port: 8765, token: 'secret');

  test('background keeps streaming and detached cleanup runs once', () async {
    final capture = FakeAudioCapture();
    final sockets = FakeSocketFactory();
    final wakelock = FakeWakelock();
    final controller = StreamingSessionController(
      audioCapture: capture,
      socketFactory: sockets,
      wakelock: wakelock,
      platformAudioResources: FakePlatformAudioResources(),
    );

    await controller.start(target);
    controller.handleLifecycleState(AppLifecycleState.inactive);
    controller.handleLifecycleState(AppLifecycleState.paused);
    await flushEvents();

    expect(
      controller.state.bridgeState,
      BridgeState.streaming,
      reason: controller.state.status,
    );
    expect(capture.stopCount, 0);
    expect(sockets.created.single.closeCount, 0);

    controller.handleLifecycleState(AppLifecycleState.detached);
    controller.handleLifecycleState(AppLifecycleState.detached);
    await flushEvents();

    expect(capture.stopCount, 1);
    expect(sockets.created.single.closeCount, 1);
    expect(wakelock.disableCount, 1);
    await controller.shutdown();
  });

  test('concurrent controls create one recorder and socket', () async {
    final capture = FakeAudioCapture();
    final sockets = FakeSocketFactory();
    final controller = StreamingSessionController(
      audioCapture: capture,
      socketFactory: sockets,
      wakelock: FakeWakelock(),
      platformAudioResources: FakePlatformAudioResources(),
    );

    await Future.wait([controller.start(target), controller.start(target)]);
    await Future.wait([controller.pause(), controller.pause()]);
    await Future.wait([controller.resume(), controller.resume()]);

    expect(
      controller.state.bridgeState,
      BridgeState.streaming,
      reason: controller.state.status,
    );
    expect(sockets.connectCount, 1);
    expect(capture.startCount, 2);
    expect(capture.maxActiveStreams, 1);
    await controller.shutdown();
  });

  test('resume reconnects when paused socket was lost', () async {
    final capture = FakeAudioCapture();
    final sockets = FakeSocketFactory();
    final controller = StreamingSessionController(
      audioCapture: capture,
      socketFactory: sockets,
      wakelock: FakeWakelock(),
      platformAudioResources: FakePlatformAudioResources(),
    );

    await controller.start(target);
    await controller.pause();
    await sockets.created.single.closeFromServer();
    await flushEvents();
    await controller.resume();

    expect(
      controller.state.bridgeState,
      BridgeState.streaming,
      reason: controller.state.status,
    );
    expect(sockets.connectCount, 2);
    expect(
      sockets.created.last.sent.whereType<String>().map(jsonDecode),
      contains(predicate((dynamic value) => value['type'] == 'resume')),
    );
    await controller.shutdown();
  });

  test('stale socket callbacks cannot alter a new session', () async {
    final capture = FakeAudioCapture();
    final sockets = FakeSocketFactory();
    final controller = StreamingSessionController(
      audioCapture: capture,
      socketFactory: sockets,
      wakelock: FakeWakelock(),
      platformAudioResources: FakePlatformAudioResources(),
    );

    await controller.start(target);
    final staleSocket = sockets.created.single;
    await controller.stop();
    await controller.start(target);
    staleSocket.emit('{type:error,message:stale}');
    await flushEvents();

    expect(
      controller.state.bridgeState,
      BridgeState.streaming,
      reason: controller.state.status,
    );
    expect(controller.state.status, isNot(contains('stale')));
    await controller.shutdown();
  });

  test('interruption recovery cannot override user pause', () async {
    final controller = StreamingSessionController(
      audioCapture: FakeAudioCapture(),
      socketFactory: FakeSocketFactory(),
      wakelock: FakeWakelock(),
      platformAudioResources: FakePlatformAudioResources(),
    );

    await controller.start(target);
    await controller.pause();
    controller.handlePlatformAudioEvent(
      const PlatformAudioEvent(
        PlatformAudioEventType.interruptionEnded,
        canResume: true,
      ),
    );

    expect(
      controller.state.bridgeState,
      BridgeState.paused,
      reason: controller.state.status,
    );
    expect(controller.state.userPaused, isTrue);
    await controller.shutdown();
  });
}

Future<void> flushEvents() => Future<void>.delayed(Duration.zero);

class FakeAudioCapture implements AudioCapture {
  final StreamController<CaptureState> _states =
      StreamController<CaptureState>.broadcast();
  bool recording = false;
  int startCount = 0;
  int stopCount = 0;
  int activeStreams = 0;
  int maxActiveStreams = 0;

  @override
  Stream<CaptureState> get stateChanges => _states.stream;

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<bool> isRecording() async => recording;

  @override
  Future<Stream<List<int>>> startStream(String targetLabel) async {
    startCount++;
    recording = true;
    activeStreams++;
    if (activeStreams > maxActiveStreams) maxActiveStreams = activeStreams;
    return const Stream<List<int>>.empty();
  }

  @override
  Future<void> resumeAfterInterruption() async {
    recording = true;
  }

  @override
  Future<void> stop() async {
    if (!recording) return;
    stopCount++;
    recording = false;
    activeStreams--;
  }

  @override
  Future<void> dispose() async {
    await _states.close();
  }
}

class FakeSocketFactory implements StreamingSocketFactory {
  final List<FakeSocket> created = [];
  int connectCount = 0;

  @override
  Future<StreamingSocket> connect(Uri uri) async {
    connectCount++;
    final socket = FakeSocket();
    created.add(socket);
    return socket;
  }
}

class FakeSocket implements StreamingSocket {
  FakeSocket() {
    _messages = StreamController<dynamic>(
      onListen: () => scheduleMicrotask(() => emit('{type:ready}')),
    );
  }

  late final StreamController<dynamic> _messages;
  final List<Object> sent = [];
  bool _open = true;
  int closeCount = 0;

  @override
  bool get isOpen => _open;

  @override
  Stream<dynamic> get messages => _messages.stream;

  @override
  void add(Object data) => sent.add(data);

  void emit(Object data) {
    if (!_messages.isClosed) _messages.add(data);
  }

  Future<void> closeFromServer() async {
    _open = false;
    await _messages.close();
  }

  @override
  Future<void> close() async {
    closeCount++;
    _open = false;
    if (!_messages.isClosed) await _messages.close();
  }
}

class FakeWakelock implements SessionWakelock {
  int enableCount = 0;
  int disableCount = 0;

  @override
  Future<void> enable() async {
    enableCount++;
  }

  @override
  Future<void> disable() async {
    disableCount++;
  }
}

class FakePlatformAudioResources implements PlatformAudioResources {
  int startCount = 0;
  int stopCount = 0;

  @override
  Stream<PlatformAudioEvent> get events =>
      const Stream<PlatformAudioEvent>.empty();

  @override
  Future<bool> prepare() async => true;

  @override
  Future<void> start(String targetLabel) async {
    startCount++;
  }

  @override
  Future<void> stop() async {
    stopCount++;
  }

  @override
  Future<void> dispose() async {}
}
