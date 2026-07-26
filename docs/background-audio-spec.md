# Mobile Background Audio Implementation Specification

Status: Proposed
Target release: Mobile Mic Bridge 0.2.x
Last updated: 2026-07-26

## 1. Context

The app currently stops recording and closes the WebSocket on `AppLifecycleState.paused` or `detached`. `wakelock_plus` prevents automatic screen sleep but does not provide background microphone execution.

This specification defines Android and iOS background behavior, lifecycle rules, failures, platform configuration, testing, and acceptance. The protocol remains 48 kHz mono PCM signed 16-bit little-endian over `/mic` WebSocket.

## 2. Goals

- Continue sending audio after app switching or screen locking.
- Restore accurate state, duration, and gain on foreground return.
- Prevent duplicate recorders, subscriptions, and WebSockets during control races.
- Stop safely after interruption, network loss, or permission revocation.
- Use an Android microphone foreground service and ongoing notification.
- Use iOS Audio Background Mode only for user-initiated recording.

## 3. Non-goals

- Continue after force-stop, iOS swipe-away, process termination, restart, or reboot.
- Bypass platform privacy restrictions or reconnect forever in the background.
- Add Android notification control actions in the first version; tapping returns to the app.
- Run discovery or QR scanning in the background.
- Change the Windows protocol, audio-device selection, or virtual cable approach.

## 4. Required behavior

### Start

Start only from the foreground. Obtain microphone permission and, where required, notification permission; complete `hello` / `ready`; start recording; then enter `streaming`. Android must display its ongoing notification before relying on background execution.

### Background and lock screen

- `streaming`: keep recorder, gain processing, and WebSocket sending active.
- `connecting` or `resuming`: cancel incomplete startup rather than initiating microphone use from the background.
- `paused`: recording is inactive. iOS may suspend the app and close the idle socket, so retention is best effort.
- `idle` or `error`: retain no background capability.

### Foreground return

- Preserve `streaming` without creating another session when recorder and socket are healthy.
- Preserve user-paused state. Resume validates the socket and reconnects and handshakes when required.
- Enter `error` with an actionable message if the platform terminated capture or connectivity.

### Stop

Cancel the audio subscription, stop the recorder, close the WebSocket, stop the Android foreground service, and release wakelock. Cleanup is idempotent and continues if one operation fails.

## 5. State and lifecycle

Keep the existing state machine:

```text
idle -> connecting -> streaming
streaming -> paused -> resuming -> streaming
connecting/resuming/streaming/paused -> error
any active state -> idle
```

Internally track `appVisibility`, `interruptionState`, and `userPaused`. Every asynchronous callback continues to reject stale `sessionId` values.

- `inactive`: do not stop; wait for a platform interruption or the next lifecycle state.
- `hidden` / `paused`: record background visibility but never call `_stopStreaming()` for an active stream.
- `resumed`: validate recorder and socket health and refresh UI.
- `detached`: request complete cleanup without assuming async work finishes before process exit.

## 6. Flutter refactor

Move recording and networking out of page State into a testable `StreamingSessionController`:

```text
mobile_app/lib/streaming/streaming_session_controller.dart
mobile_app/lib/streaming/streaming_session_state.dart
mobile_app/lib/streaming/platform_audio_events.dart
```

The controller owns the handshake, recorder lifecycle, PCM gain and sending, serialized controls, session validation, reconnect-on-resume behavior, and immutable UI state. Exactly one recorder stream, audio subscription, and active WebSocket may exist.

## 7. Android

Add to `mobile_app/tool/AndroidManifest.xml`:

```xml
<uses-permission android:name=android.permission.FOREGROUND_SERVICE />
<uses-permission android:name=android.permission.FOREGROUND_SERVICE_MICROPHONE />
<uses-permission android:name=android.permission.POST_NOTIFICATIONS />
```

The recording service declares `android:foregroundServiceType=microphone`. Start it while the app is visible and microphone permission is granted, never for the first time after the app is already backgrounded.

- Keep `record` pinned to `6.2.1` and use that version's background recording/foreground service support.
- Revalidate this capability before upgrading the dependency.
- Bind service lifetime and notification truthfully to active capture.
- Use a stable, low-importance notification channel with clear microphone-streaming text.
- Tapping the notification opens the existing `singleTop` `MainActivity` and session.
- Do not restart recording automatically after process death.
- Stop and report an error after permission revocation or recorder loss.

Suggested notification: `Mobile Mic Bridge — Streaming microphone to <computer name or IP>`.

## 8. iOS

Add to `mobile_app/tool/Info.plist`:

```xml
<key>UIBackgroundModes</key>
<array>
    <string>audio</string>
</array>
```

- Use an `AVAudioSession` category that supports recording; use `playAndRecord` only when playback is required.
- Activate the session before recording and deactivate it after complete stop.
- Listen for calls, Siri, alarms, route changes, Bluetooth changes, and microphone loss.
- Keep system interruption distinct from user pause.
- Auto-resume only when the session was streaming, the system permits resume, and the session is still valid.
- Active recording may continue while locked or backgrounded; a user-paused socket is not guaranteed to survive.
- Force-stop, swipe-away, or process termination ends the session.
- Do not use silent playback, unrelated background modes, or timer traffic as keepalive mechanisms.

## 9. Pause and resume

Pause blocks new PCM frames, waits for a pending recorder start, cancels the subscription, stops the recorder, sends `pause` when connected, and retains target, port, token, gain, and duration.

Resume serializes repeated requests and validates the WebSocket. If invalid, reconnect and complete `hello` / `ready`; then send `resume` and create exactly one recorder stream and subscription. Failure ends in retryable `paused` or `error`, never indefinitely in `resuming`.

## 10. Network and errors

- Do not add unlimited background reconnect in the first release.
- Socket loss while streaming stops capture, releases background resources, and enters `error`.
- Socket loss while paused preserves paused state and reconnects on user resume.
- Do not attempt a LAN address after moving to cellular-only connectivity.
- Never include the token in errors, logs, or notifications.
- Continue cleanup after individual cleanup failures.

## 11. Privacy

Enable the microphone only after an explicit foreground action. Android's ongoing notification and iOS's microphone indicator must reflect capture truthfully. Keep tokens in memory only. Do not run camera, QR, or new discovery operations in the background. Continue to disclose that LAN PCM is currently unencrypted and the token controls access only.

## 12. Test plan

### Flutter

- Background lifecycle does not stop a streaming session; detached cleanup runs once.
- Repeated or concurrent controls do not duplicate resources.
- Resume reconnects after a paused socket is lost.
- Stale `sessionId` callbacks cannot alter the current session.
- Interruption recovery cannot override a user pause.

### Android devices

- Lock screen and switch apps for 10 minutes each while Windows receives uninterrupted audio.
- Verify notification and microphone permission denial, revocation, and force-stop behavior.
- Verify notification navigation returns to the active session.
- Pause, lock, return, and resume without duplicated or accelerated audio.

### iOS devices

- Lock screen and switch apps for 10 minutes each while Windows receives uninterrupted audio.
- Verify call/Siri interruption recovery or an actionable failure.
- Change wired, Bluetooth, and built-in routes without crashing.
- Verify swipe-away stops capture and networking.
- Resume and reconnect after a long background pause.

### Windows integration

- Preserve audio format, channels, and sample rate.
- Clear receiver jitter buffer on pause/resume with no stale playback.
- Stream for 30 minutes without duplicate frames, session conflicts, or obvious memory growth.

## 13. CI and release

Apply platform changes to templates because `mobile_app/tool/bootstrap.ps1` generates platform directories from them. CI runs `flutter analyze` and `flutter test`. Release builds verify the merged Android manifest contains the microphone foreground service type and the built iOS plist contains `UIBackgroundModes/audio`. Release notes disclose background limitations and microphone indicators.

## 14. Implementation order

1. Extract and test `StreamingSessionController`.
2. Remove lifecycle-driven stop on background entry.
3. Add the Android microphone foreground service and notification.
4. Add iOS Audio Background Mode and interruption handling.
5. Add reconnect-on-resume for paused sessions.
6. Update device checklists and bilingual user documentation.
7. Complete long-running Android, iOS, and Windows integration tests.

## 15. Acceptance criteria

- Android and iOS transmit uninterrupted audio for 10 minutes while locked or backgrounded on stable Wi-Fi.
- Android always shows a compliant foreground-service notification during background capture.
- Foreground return never creates a second connection or recorder stream.
- Pause always resumes; a socket closed during pause is re-handshaken.
- Stop releases recorder, WebSocket, wakelock, and Android service within two seconds.
- Permission loss, network loss, and audio interruption never crash or permanently hang a transition.
- Flutter tests, Android build, and unsigned iOS build pass.
