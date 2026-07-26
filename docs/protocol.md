# Wire Protocol / 传输协议

## Transport / 传输层

- WebSocket endpoint: `/mic`
- Default TCP port: `8765`
- One active client at a time
- Text frames carry control JSON
- Binary frames carry raw audio bytes
- Maximum WebSocket message size: 256 KiB

WebSocket 地址为 `/mic`，默认 TCP 端口为 `8765`。文本帧传输控制 JSON，二进制帧传输原始音频。同一时间只接受一个手机连接。

The Windows receiver advertises `_mobilemic._tcp.local.` with mDNS/DNS-SD. The service TXT record contains protocol version and audio format metadata, but never contains the connection password.

Windows 接收端通过 mDNS/DNS-SD 广播 `_mobilemic._tcp.local.`。TXT 记录只包含协议版本和音频格式，不包含连接密码。

## QR Pairing / 二维码配对

When the receiver starts, it may print an ASCII QR code containing a URI in this form:

```text
mobilemic://connect?host=192.168.1.20&port=8765&token=optional
```

The mobile app validates the scheme, host, port, and optional token before filling the connection form. The QR token is used for the current session but is not persisted by the app.

接收端启动时可以在终端显示 ASCII 二维码，其内容使用上述 `mobilemic://` URI。手机会校验协议、地址、端口和可选密码后填写连接表单。二维码中的密码只用于当前运行，不会持久化。

## Handshake / 握手

The first frame must be a JSON object with these fields:

首帧必须是包含下列字段的 JSON 对象：

| Field | Required value | 说明 |
| --- | --- | --- |
| `type` | `hello` | 消息类型 |
| `version` | `1` | 协议版本 |
| `sampleRate` | `48000` | 采样率 |
| `channels` | `1` | 单声道 |
| `format` | `pcm_s16le` | 16 位小端 PCM |
| `token` | optional string | 可选连接密码 |
| `device` | platform string | 手机平台信息 |

The server responds with a JSON object whose type is `ready`, or an error object containing a human-readable message. The sender must wait for `ready` before starting audio capture. An error closes the connection with WebSocket policy code `1008`.

服务端返回类型为 `ready` 的 JSON 对象，或带有人类可读消息的错误对象。发送端必须收到 `ready` 后才能开始录音。错误会使用 WebSocket 策略错误码 `1008` 关闭连接。

## Audio / 音频

- Sample rate: 48000 Hz
- Channels: mono
- Sample format: signed 16-bit little-endian PCM
- Recommended packet duration: about 10 to 40 ms
- No per-packet header; frame order is WebSocket order
- A PCM sample may span two WebSocket messages; receivers preserve incomplete trailing bytes

音频固定为 48 kHz、单声道、16 位小端有符号 PCM。建议每个二进制帧携带约 10 到 40 毫秒音频。音频帧没有额外包头，顺序就是 WebSocket 的可靠传输顺序。

## Pause and Resume / 暂停与继续

The phone keeps the WebSocket connection open while paused and sends a text control frame whose type is `pause`. On resume it sends type `resume` and restarts microphone capture. The receiver clears its jitter buffer for both messages.

手机暂停时保持 WebSocket 连接，仅停止麦克风采集并发送类型为 `pause` 的文本控制帧。继续时发送 `resume` 并重新启动录音。接收端收到两种消息时都会清空抖动缓冲。

## Compatibility / 兼容性

Receivers must reject unsupported protocol versions or audio formats. Future versions may add codec negotiation, timestamps, sequence numbers, device discovery, and TLS.

接收端必须拒绝不支持的协议版本或音频格式。后续版本可以加入编码协商、时间戳、序列号、设备发现与 TLS。
