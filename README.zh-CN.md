# Mobile Mic Bridge

[English](README.md)

让 Android 或 iOS 手机通过 Wi-Fi 充当 Windows 电脑的低延迟麦克风。

手机端采集单声道 PCM 音频，通过局域网 WebSocket 发送到 Windows 接收端。接收端把音频播放到指定输出设备；选择虚拟音频线作为输出后，Discord、OBS、游戏、会议软件和浏览器就可以把对应的虚拟输入设备当作麦克风。

## 功能

- Flutter 手机端同时支持 Android 与 iOS
- 48 kHz、单声道、16 位有符号 PCM
- 带欠载恢复的有界抖动缓冲
- 可选连接密码
- 通过 mDNS/DNS-SD 自动发现 Windows 接收端
- 自动发现失败时可扫描 Windows 终端二维码
- 记住上次电脑地址、端口和发送音量
- 手机端 0% 到 200% 发送音量控制
- 不断开连接即可重复暂停和继续
- Windows 可选择音频输出设备
- 自动构建 Android APK、未签名 iOS 应用归档和 Windows x64/ARM64 EXE
- 中英文文档

## 工作原理

```text
手机麦克风
    |
    | PCM16 / WebSocket / Wi-Fi
    v
Windows 接收端
    |
    | 播放到指定输出
    v
虚拟音频线输入  ->  虚拟音频线输出  ->  Windows 软件的麦克风
```

Windows 普通应用无法在不安装签名音频驱动的情况下创建系统麦克风端点，因此需要安装 VB-CABLE 或同类虚拟音频设备。本项目保持在用户态运行，不包含内核驱动。

## 快速开始

### 1. 配置 Windows

1. 安装 Python 3.10 或更高版本。
2. 安装虚拟音频线。以 VB-CABLE 为例，接收端输出到 `CABLE Input`，语音软件把 `CABLE Output` 选为麦克风。
3. 在 `windows_receiver` 目录打开 PowerShell。
4. 创建虚拟环境并安装接收端：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

5. 查看可用输出设备：

```powershell
mobile-mic-receiver --list-devices
```

6. 使用列表中的设备编号启动接收端：

```powershell
mobile-mic-receiver --device 12 --token 自定义密码
```

Windows 防火墙弹窗出现时，允许 TCP 端口 `8765` 通过专用网络。接收端会输出可以填写到手机上的本机 IPv4 地址。

### 2. 构建手机端

安装 Flutter，然后运行：

```powershell
cd mobile_app
.\tool\bootstrap.ps1
flutter run
```

iOS 构建需要 macOS、Xcode、Apple 开发团队和正常的代码签名；Android 可以在 Windows、macOS 或 Linux 上构建。

### 3. 建立连接

1. 手机和电脑连接同一个 Wi-Fi。
2. 点击自动发现的电脑、扫描 Windows 终端二维码，或手动填写 IPv4 地址和端口 `8765`。
3. 点击 `开始传输`。
4. 在 Discord、OBS 或其他目标软件中，把虚拟音频线输出选为麦克风。

传输期间应用会保持屏幕常亮。当前 MVP 切到后台仍会停止会话。建议使用耳机，避免电脑扬声器声音再次被手机收录而形成回声。

音量滑杆控制发送到 Windows 的 PCM 电平。`100%` 保持原始音量，`0%` 静音，超过 `100%` 时较大的声音可能削波失真。

应用会记住上次连接的电脑地址、端口和音量。连接密码只保留在本次运行内存中，不会持久化保存。

## 接收端参数

```text
--host            监听地址，默认 0.0.0.0
--port            WebSocket 端口，默认 8765
--device          输出设备编号或名称
--token           可选连接密码
--latency-ms      最大缓冲时长，默认 400
--prebuffer-ms    启动和恢复预缓冲，默认 80
--no-discovery    关闭 mDNS 自动发现广播
--no-qr           不在终端显示配对二维码
--list-devices    列出输出设备后退出
```

降低 `--prebuffer-ms` 可以减少延迟，但 Wi-Fi 不稳定时更容易爆音。建议从 60 到 120 毫秒开始调整。
`--prebuffer-ms` 不能大于 `--latency-ms`。

## 安全说明

- 当前设计用于可信任的家庭或办公局域网。
- 默认 `ws://` 连接没有加密。
- 建议设置 `--token`，防止局域网其他设备误连接。
- 不要把端口 `8765` 直接暴露到公网。

## 开发与测试

```powershell
cd windows_receiver
python -m pip install -e .[test]
python -m pytest -q
```

```powershell
cd mobile_app
flutter analyze
flutter test
```

传输协议见 `docs/protocol.md`。

## 自动发布

推送 `v0.1.1` 这类新标签会触发 `.github/workflows/release.yml`，并发布 Android APK、Windows x64/ARM64 单文件 EXE 和未签名 iOS Runner 应用归档。

GitHub Actions 无法在没有项目专属 Apple 证书和描述文件的情况下生成可直接安装的签名 IPA。

## 当前限制

- 同一时间只允许一台手机连接。
- PCM 没有压缩，WebSocket 开销前的典型带宽约为 768 kbit/s。
- 当前传输针对局域网优化，不适合直接穿透公网。
- Windows 需要另行安装虚拟音频线，才能作为系统麦克风使用。
