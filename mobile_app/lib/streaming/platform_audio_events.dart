import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import 'streaming_session_state.dart';

enum PlatformAudioEventType {
  interruptionBegan,
  interruptionEnded,
  routeChanged,
  microphoneUnavailable,
}

class PlatformAudioEvent {
  const PlatformAudioEvent(this.type, {this.canResume = false});

  final PlatformAudioEventType type;
  final bool canResume;
}

AppVisibility appVisibilityForLifecycle(AppLifecycleState state) {
  return switch (state) {
    AppLifecycleState.resumed => AppVisibility.foreground,
    AppLifecycleState.inactive => AppVisibility.inactive,
    AppLifecycleState.detached => AppVisibility.detached,
    AppLifecycleState.hidden ||
    AppLifecycleState.paused => AppVisibility.background,
  };
}

abstract interface class PlatformAudioResources {
  Stream<PlatformAudioEvent> get events;
  Future<bool> prepare();
  Future<void> start(String targetLabel);
  Future<void> stop();
  Future<void> dispose();
}

class MethodChannelPlatformAudioResources implements PlatformAudioResources {
  static const MethodChannel _channel =
      MethodChannel('mobile_mic_bridge/background_audio');
  final StreamController<PlatformAudioEvent> _events =
      StreamController<PlatformAudioEvent>.broadcast();

  MethodChannelPlatformAudioResources() {
    _channel.setMethodCallHandler((call) async {
      if (call.method != 'audioEvent') return;
      final arguments = call.arguments;
      if (arguments is! Map) return;
      switch (arguments['type']) {
        case 'interruptionBegan':
          _events.add(
            const PlatformAudioEvent(PlatformAudioEventType.interruptionBegan),
          );
          break;
        case 'interruptionEnded':
          _events.add(PlatformAudioEvent(
            PlatformAudioEventType.interruptionEnded,
            canResume: arguments['canResume'] == true,
          ));
          break;
        case 'routeChanged':
          _events.add(
            const PlatformAudioEvent(PlatformAudioEventType.routeChanged),
          );
          break;
        case 'microphoneUnavailable':
          _events.add(const PlatformAudioEvent(
            PlatformAudioEventType.microphoneUnavailable,
          ));
          break;
      }
    });
  }

  @override
  Stream<PlatformAudioEvent> get events => _events.stream;

  @override
  Future<bool> prepare() async {
    if (!Platform.isAndroid) return true;
    final granted = await _channel.invokeMethod<bool>(
      'requestNotificationPermission',
    );
    return granted == true;
  }

  @override
  Future<void> start(String targetLabel) async {
    if (!Platform.isAndroid) return;
    await _channel.invokeMethod<void>(
      'startForegroundService',
      <String, Object>{'target': targetLabel},
    );
  }

  @override
  Future<void> stop() async {
    if (!Platform.isAndroid) return;
    await _channel.invokeMethod<void>('stopForegroundService');
  }

  @override
  Future<void> dispose() async {
    _channel.setMethodCallHandler(null);
    await _events.close();
  }
}
