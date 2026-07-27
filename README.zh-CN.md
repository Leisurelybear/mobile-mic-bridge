# Mobile Mic Bridge

[English](README.md)

让 Android 或 iOS 手机通过 Wi-Fi 充当 Windows 电脑的低延迟麦克风。

手机端 Flutter 应用或**接收端内置网页**采集单声道 PCM 音频，通过局域网 WebSocket 发送到 Windows 接收端。接收端把音频播放到指定输出设备；选择虚拟音频线作为输出后，Discord、OBS、游戏、会议软件和浏览器就可以把对应的虚拟输入设备当作麦克风。

## 功能

- Flutter 手机端同时支持 Android 与 iOS
- **网页麦克风**：接收端托管页面，扫码即可用，无需安装 App
- 48 kHz、单声道、16 位有符号 PCM
- 带欠载恢复的有界抖动缓冲
- 可选连接密码
- 通过 mDNS/DNS-SD 自动发现 Windows 接收端
- Windows 图形界面接收端，内置配对二维码与电平显示
- 默认展示网页配对二维码，也可切换为 Flutter App 二维码
- 记住上次电脑地址、端口和发送音量
- 手机端 0% 到 200% 发送音量控制
- 不断开连接即可重复暂停和继续
- Windows 可选择音频输出设备
- 自动构建 Android APK、未签名 iOS 应用归档和 Windows x64/ARM64 图形界面 EXE
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

1. 安装虚拟音频线。以 VB-CABLE 为例，接收端输出到 `CABLE Input`，语音软件把 `CABLE Output` 选为麦克风。
2. 从 [Releases](https://github.com/Leisurelybear/mobile-mic-bridge/releases) 下载 `mobile-mic-receiver-windows-x64.exe`（ARM 电脑下载 ARM64 版本）。
3. 双击运行接收端图形界面。
4. 选择输出设备（例如 `CABLE Input`），设置连接密码，点击 **启动接收**。
5. Windows 防火墙弹窗出现时，允许 TCP 端口 `8765` 通过专用网络。
6. 窗口会显示本机地址和**网页配对二维码**（`http://...:8765/`）。

设置会保存在 `%APPDATA%\MobileMicBridge\settings.json`，包括连接密码（明文本地存储，仅图方便，不是保险库）。

#### 开发者：从源码运行

```powershell
cd windows_receiver
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
mobile-mic-receiver-gui
```

命令行入口仍可用：

```powershell
mobile-mic-receiver --list-devices
mobile-mic-receiver --device 12 --token 自定义密码
```

### 2. 用手机浏览器连接（推荐，免装 App）

1. 手机和电脑连接同一个 Wi-Fi。
2. 扫描 Windows 窗口中的 **网页** 二维码（或打开 `http://电脑IP:8765/?token=...`）。
3. 允许麦克风权限，尽量保持页面在前台，点击 **开始传输**。
4. 建议佩戴耳机，减少电脑扬声器声音再次被手机收录。浏览器默认开启回声消除、噪音抑制和自动增益。
5. 在 Discord、OBS 或其他目标软件中，把虚拟音频线输出选为麦克风。

浏览器后台录音仅为**尽力而为**：锁屏或切走应用后可能中断（尤其 iOS Safari）。二维码中的连接密码只留在当前页面内存，不会写入本地存储。

### 3. 或构建 Flutter 手机端

安装 Flutter，然后运行：

```powershell
cd mobile_app
.\tool\bootstrap.ps1
flutter run
```

iOS 构建需要 macOS、Xcode、Apple 开发团队和正常的代码签名；Android 可以在 Windows、macOS 或 Linux 上构建。

在 Windows 图形界面把二维码切换到 **App**（或使用 `--qr-mode app`）可显示 `mobilemic://` 配对码。

1. 手机和电脑连接同一个 Wi-Fi。
2. 点击自动发现的电脑、扫描 App 二维码，或手动填写 IPv4 地址和端口 `8765`。
3. 点击 `开始传输`。
4. 在 Discord、OBS 或其他目标软件中，把虚拟音频线输出选为麦克风。

Flutter 应用切到后台或锁屏后会继续传输。Android 会显示持续的麦克风通知，iOS 使用音频后台模式；用户主动暂停后仍保持暂停，强制停止、划掉应用或进程终止会结束会话。建议使用耳机，避免电脑扬声器声音再次被手机收录而形成回声。

音量滑杆控制发送到 Windows 的 PCM 电平。`100%` 保持原始音量，`0%` 静音，超过 `100%` 时较大的声音可能削波失真。

应用会记住上次连接的电脑地址、端口和音量。连接密码只保留在本次运行内存中，不会持久化保存。

## 接收端命令行参数

命令行开发入口 `mobile-mic-receiver` 支持：

```text
--host            监听地址，默认 0.0.0.0
--port            WebSocket 端口，默认 8765
--device          输出设备编号或名称
--token           可选连接密码
--latency-ms      最大缓冲时长，默认 400
--prebuffer-ms    启动和恢复预缓冲，默认 80
--no-discovery    关闭 mDNS 自动发现广播
--no-qr           不在终端显示配对二维码
--qr-mode         web|app|both（默认网页 URL）
--list-devices    列出输出设备后退出
```

图形界面中的端口、密码、延迟、预缓冲和 mDNS 开关与上述含义相同，并提供网页 / App 二维码切换。

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

传输协议见 `docs/protocol.md`，手机后台录音行为和限制见 `docs/background-audio-spec.zh-CN.md`。局域网 PCM 目前仍未加密；连接密码只控制访问，不会加密音频。

## 自动发布

推送 `v0.1.1` 这类新标签会触发 `.github/workflows/release.yml`，并发布 Android APK、Windows x64/ARM64 单文件 EXE 和未签名 iOS Runner 应用归档。

GitHub Actions 无法在没有项目专属 Apple 证书和描述文件的情况下生成可直接安装的签名 IPA。

## 当前限制

- 同一时间只允许一台手机连接。
- PCM 没有压缩，WebSocket 开销前的典型带宽约为 768 kbit/s。
- 当前传输针对局域网优化，不适合直接穿透公网。
- Windows 需要另行安装虚拟音频线，才能作为系统麦克风使用。
- 网页端不保证后台或锁屏后继续录音，请尽量保持页面在前台。
- 浏览器回声消除效果因机型/系统而异，仍建议佩戴耳机。
- iOS Safari 支持为尽力而为，通常不如 Android Chrome 稳定。
