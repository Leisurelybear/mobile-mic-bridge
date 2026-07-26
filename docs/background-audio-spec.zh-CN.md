# 手机后台录音实现规范

状态：拟实现
适用版本：Mobile Mic Bridge 0.2.x
最后更新：2026-07-26

## 1. 背景与现状

当前手机端在进入 `AppLifecycleState.paused` 或 `detached` 时主动停止录音并关闭 WebSocket，因此切换应用或锁屏后不能继续作为麦克风使用。`wakelock_plus` 只能阻止屏幕自动休眠，不能提供真正的后台录音能力。

本规范定义 Android 和 iOS 的后台录音行为、生命周期、错误处理、平台配置和验收标准。音频格式与现有协议保持不变：48 kHz、单声道、PCM signed 16-bit little-endian，经 `/mic` WebSocket 发送到 Windows。

## 2. 目标

- 开始传输后，切换应用或锁屏时仍持续向 Windows 发送音频。
- 返回前台后准确显示传输状态、时长和音量增益。
- 暂停、继续和停止不会创建重复 recorder、音频订阅或 WebSocket。
- 后台期间发生音频中断、网络断开或权限撤销时安全停止并显示原因。
- Android 使用麦克风前台服务和常驻通知。
- iOS 只在用户明确开始录音后使用 Audio Background Mode。

## 3. 非目标

- App 被强制停止、从 iOS 多任务界面划掉或设备重启后继续录音。
- 绕过平台隐私限制或在后台无限自动重连。
- 第一版不提供 Android 通知栏暂停、继续和停止按钮；点击通知返回应用控制。
- 第一版不在后台执行自动发现或二维码扫描。
- 不改变 Windows 接收协议、音频设备选择或虚拟声卡方案。

## 4. 用户体验

### 4.1 开始

1. 用户在前台选择接收端并点击“开始传输”。
2. 应用申请麦克风权限，Android 13 及以上按需申请通知权限。
3. WebSocket 完成 `hello` / `ready` 握手。
4. 录音成功启动后进入 `streaming`；Android 同时显示常驻通知。
5. 只有上述步骤成功后，应用才允许进入后台持续工作。

### 4.2 后台与锁屏

- `streaming`：保持录音、PCM 增益处理和 WebSocket 发送。
- `connecting` 或 `resuming`：进入后台时取消未完成的启动，不承诺在后台首次启动麦克风。
- `paused`：录音已停止。iOS 可能挂起应用并关闭空闲连接，因此连接仅为尽力保持。
- `idle` 或 `error`：不保留后台能力。

### 4.3 返回前台

- recorder 和连接仍有效时保持 `streaming`，不重新创建会话。
- 用户此前主动暂停时保持 `paused`。点击“继续”先检查 WebSocket；连接失效则重新握手，再启动录音。
- 系统已终止录音或连接时进入 `error`，显示可操作错误并允许重新开始。

### 4.4 停止

用户停止、权限被撤销、发生不可恢复错误或 App 被销毁时，依次取消音频订阅、停止 recorder、关闭 WebSocket、停止 Android 前台服务并释放 wakelock。清理必须可重复调用。

## 5. 状态机与生命周期

```text
idle -> connecting -> streaming
streaming -> paused -> resuming -> streaming
connecting/resuming/streaming/paused -> error
任意活动状态 -> idle
```

新增 `appVisibility`、`interruptionState` 和 `userPaused`。所有异步回调继续校验 `sessionId`，旧会话不得修改新会话。

- `inactive`：不停止，等待平台中断事件或后续生命周期状态。
- `hidden` / `paused`：只记录进入后台；`streaming` 时不得调用 `_stopStreaming()`。
- `resumed`：检查 recorder 和 WebSocket 状态并刷新 UI。
- `detached`：请求完整清理，但不假设异步清理一定能在进程退出前结束。

## 6. Flutter 结构调整

把录音和网络生命周期从页面 State 抽离为可测试的 `StreamingSessionController`：

```text
mobile_app/lib/streaming/streaming_session_controller.dart
mobile_app/lib/streaming/streaming_session_state.dart
mobile_app/lib/streaming/platform_audio_events.dart
```

控制器负责 WebSocket 握手、录音生命周期、PCM 增益和发送、操作串行化、会话校验、继续时重连以及向 UI 暴露不可变状态。同一时间只能存在一个 recorder 流、一个音频订阅和一个活动 WebSocket。

## 7. Android 实现

在 `mobile_app/tool/AndroidManifest.xml` 增加：

```xml
<uses-permission android:name=android.permission.FOREGROUND_SERVICE />
<uses-permission android:name=android.permission.FOREGROUND_SERVICE_MICROPHONE />
<uses-permission android:name=android.permission.POST_NOTIFICATIONS />
```

录音服务必须声明 `android:foregroundServiceType=microphone`。服务必须在应用可见且麦克风权限已授予时启动，不能等应用进入后台后才首次启动。

- 保持 `record` 固定在 `6.2.1`，使用该版本的 Android 后台录音/前台服务能力。
- 升级 `record` 前必须重新验证后台能力，不能仅依赖语义版本自动升级。
- 前台服务和活动录音绑定；停止录音后不能留下虚假的麦克风通知。
- 使用稳定、低重要级别的通知渠道，通知明确显示正在传输麦克风。
- 点击通知打开现有 `singleTop` `MainActivity` 并复用当前会话。
- 系统杀死进程后不自动恢复录音。
- 麦克风权限被撤销或录音设备不可用时立即停止并进入错误状态。

建议通知：`Mobile Mic Bridge — 正在将麦克风传输到 <电脑名称或 IP>`。

## 8. iOS 实现

在 `mobile_app/tool/Info.plist` 增加：

```xml
<key>UIBackgroundModes</key>
<array>
    <string>audio</string>
</array>
```

- 使用支持录音的 `AVAudioSession` category；只有确有播放需求时才使用 `playAndRecord`。
- 开始录音前激活音频会话，完整停止后释放或停用。
- 监听电话、Siri、闹钟、蓝牙变化和麦克风不可用等中断与路由变化。
- 系统中断不能被误记为用户暂停。
- 仅在中断前为 `streaming`、系统允许恢复且会话仍有效时自动恢复，否则显示错误。
- 活跃录音可在锁屏和切换应用后继续；用户主动暂停后 WebSocket 不保证存活。
- 划掉应用、强制停止或系统终止进程后不能继续。
- 不使用无声循环、无关后台模式或定时网络请求保活。

## 9. 暂停与继续

暂停必须阻止新 PCM 帧、等待 pending recorder start、取消音频订阅、停止 recorder、在连接有效时发送 `pause`，并保留目标地址、端口、token、增益和持续时长。

继续必须串行化重复请求并检查 WebSocket。连接失效时重新连接并完成 `hello` / `ready`，然后发送 `resume`，启动唯一的 recorder 和音频订阅。失败必须回到 `error` 或可重试的 `paused`，不能永久卡在 `resuming`。

## 10. 网络与错误处理

- 第一版不做无限后台自动重连。
- `streaming` 时 WebSocket 断开：停止 recorder，释放后台能力并进入 `error`。
- `paused` 时连接断开：保持暂停并标记需要重连，点击继续时重新连接。
- 切换到仅移动网络时不尝试访问局域网接收端，显示“接收端不可达”。
- 错误、日志和通知不得包含 token。
- 任意清理步骤失败不能阻止其余资源释放。

## 11. 安全与隐私

- 只有用户在前台明确点击开始后才启用麦克风。
- Android 常驻通知和 iOS 麦克风指示器必须真实反映录音状态。
- token 只保存在内存中，不写入 SharedPreferences、日志或通知。
- 后台时不得自动打开相机、扫描二维码或开始新的设备发现。
- UI 和文档继续说明局域网 PCM 当前未加密，token 只用于接入控制。

## 12. 测试计划

### Flutter 单元测试

- 后台生命周期不停止活动的 streaming 会话；`detached` 只清理一次。
- 重复或并发 start/stop/pause/resume 不创建重复资源。
- paused 状态连接失效后，继续会重新握手。
- 旧 `sessionId` 回调不能影响新会话。
- 系统中断恢复不会覆盖用户主动暂停。

### Android 真机测试

- 锁屏和切换其他应用各 10 分钟，Windows 持续收到音频。
- 拒绝通知权限、撤销麦克风权限和强制停止均有预期结果。
- 通知存在且点击可返回当前会话。
- 暂停、锁屏、返回、继续不会产生重复或加速音频。

### iOS 真机测试

- 锁屏和切换应用各 10 分钟，Windows 持续收到音频。
- 电话/Siri 中断后正确恢复或报错。
- 切换有线、蓝牙和内置麦克风时不崩溃。
- 划掉应用后录音和网络停止。
- 暂停后长时间后台，再返回并继续时可以重新连接。

### Windows 联调

- 后台期间音频格式、声道和采样率不变化。
- 暂停和继续会清空接收端抖动缓冲，恢复后无旧音频回放。
- 连续传输 30 分钟无明显内存增长、重复帧或多会话冲突。

## 13. CI 与发布

- `mobile_app/tool/bootstrap.ps1` 会复制平台模板，权限和后台配置必须首先修改模板文件。
- CI 运行 `flutter analyze` 和 `flutter test`。
- Android Release 构建验证合并后的 Manifest 包含 microphone foreground service type。
- iOS unsigned build 验证最终 `Info.plist` 包含 `UIBackgroundModes/audio`。
- Release Notes 说明后台录音限制和持续麦克风指示。

## 14. 建议实施顺序

1. 抽离并测试 `StreamingSessionController`。
2. 修改 Flutter 生命周期，取消进入后台时自动停止。
3. 实现 Android 麦克风前台服务和通知。
4. 实现 iOS Audio Background Mode 和中断处理。
5. 完善暂停后重连逻辑。
6. 增加真机测试清单和中英文用户文档。
7. 完成 Android、iOS 和 Windows 长时间联调。

## 15. 验收标准

- Android 和 iOS 在稳定 Wi-Fi 下锁屏或切换应用 10 分钟，Windows 音频不中断。
- Android 后台录音期间始终存在符合系统要求的前台服务通知。
- 返回前台不会创建第二个连接或第二个 recorder 流。
- 暂停后可以继续；暂停期间连接被关闭时，继续会自动重新握手。
- 用户停止后 2 秒内关闭 recorder、WebSocket、wakelock 和 Android 前台服务。
- 权限撤销、网络断开和音频中断不会崩溃或永久卡在过渡状态。
- Flutter 测试、Android 构建和 iOS unsigned 构建全部通过。
