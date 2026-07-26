import AVFoundation
import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
    private var backgroundAudioChannel: FlutterMethodChannel?

    override func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        GeneratedPluginRegistrant.register(with: self)
        let didFinishLaunching = super.application(
            application,
            didFinishLaunchingWithOptions: launchOptions
        )
        if let controller = window?.rootViewController as? FlutterViewController {
            backgroundAudioChannel = FlutterMethodChannel(
                name: "mobile_mic_bridge/background_audio",
                binaryMessenger: controller.binaryMessenger
            )
        }
        let center = NotificationCenter.default
        center.addObserver(
            self,
            selector: #selector(handleAudioInterruption(_:)),
            name: AVAudioSession.interruptionNotification,
            object: nil
        )
        center.addObserver(
            self,
            selector: #selector(handleRouteChange(_:)),
            name: AVAudioSession.routeChangeNotification,
            object: nil
        )
        center.addObserver(
            self,
            selector: #selector(handleMediaServicesReset(_:)),
            name: AVAudioSession.mediaServicesWereResetNotification,
            object: nil
        )
        return didFinishLaunching
    }

    @objc private func handleAudioInterruption(_ notification: Notification) {
        guard let rawType = notification.userInfo?[AVAudioSessionInterruptionTypeKey]
                as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: rawType) else {
            return
        }
        if type == .began {
            sendAudioEvent(type: "interruptionBegan")
            return
        }
        let rawOptions = notification.userInfo?[AVAudioSessionInterruptionOptionKey]
            as? UInt ?? 0
        let canResume = AVAudioSession.InterruptionOptions(rawValue: rawOptions)
            .contains(.shouldResume)
        sendAudioEvent(type: "interruptionEnded", canResume: canResume)
    }

    @objc private func handleRouteChange(_ notification: Notification) {
        sendAudioEvent(type: "routeChanged")
    }

    @objc private func handleMediaServicesReset(_ notification: Notification) {
        sendAudioEvent(type: "microphoneUnavailable")
    }

    private func sendAudioEvent(type: String, canResume: Bool = false) {
        backgroundAudioChannel?.invokeMethod(
            "audioEvent",
            arguments: ["type": type, "canResume": canResume]
        )
    }
}
