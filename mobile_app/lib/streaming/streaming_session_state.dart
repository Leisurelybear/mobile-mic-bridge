enum BridgeState { idle, connecting, streaming, paused, resuming, error }

enum AppVisibility { foreground, inactive, background, detached }

enum InterruptionState { none, interrupted }

class StreamingSessionState {
  const StreamingSessionState({
    this.bridgeState = BridgeState.idle,
    this.status = '输入 Windows 电脑的局域网 IP',
    this.duration = Duration.zero,
    this.gain = 1,
    this.appVisibility = AppVisibility.foreground,
    this.interruptionState = InterruptionState.none,
    this.userPaused = false,
  });

  final BridgeState bridgeState;
  final String status;
  final Duration duration;
  final double gain;
  final AppVisibility appVisibility;
  final InterruptionState interruptionState;
  final bool userPaused;

  StreamingSessionState copyWith({
    BridgeState? bridgeState,
    String? status,
    Duration? duration,
    double? gain,
    AppVisibility? appVisibility,
    InterruptionState? interruptionState,
    bool? userPaused,
  }) {
    return StreamingSessionState(
      bridgeState: bridgeState ?? this.bridgeState,
      status: status ?? this.status,
      duration: duration ?? this.duration,
      gain: gain ?? this.gain,
      appVisibility: appVisibility ?? this.appVisibility,
      interruptionState: interruptionState ?? this.interruptionState,
      userPaused: userPaused ?? this.userPaused,
    );
  }
}
