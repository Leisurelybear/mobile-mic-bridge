package com.example.mobile_mic_bridge

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var pendingPermissionResult: MethodChannel.Result? = null
    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            pendingPermissionResult?.success(
                granted && NotificationManagerCompat.from(this).areNotificationsEnabled()
            )
            pendingPermissionResult = null
        }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "mobile_mic_bridge/background_audio"
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "requestNotificationPermission" -> requestNotificationPermission(result)
                "startForegroundService" -> {
                    val target = call.argument<String>("target").orEmpty()
                    val intent = Intent(this, MicrophoneForegroundService::class.java)
                        .putExtra(MicrophoneForegroundService.EXTRA_TARGET, target)
                    ContextCompat.startForegroundService(this, intent)
                    result.success(null)
                }
                "stopForegroundService" -> {
                    stopService(Intent(this, MicrophoneForegroundService::class.java))
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun requestNotificationPermission(result: MethodChannel.Result) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            result.success(NotificationManagerCompat.from(this).areNotificationsEnabled())
            return
        }
        if (ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            result.success(NotificationManagerCompat.from(this).areNotificationsEnabled())
            return
        }
        if (pendingPermissionResult != null) {
            result.error("permission_pending", "Notification permission request is pending", null)
            return
        }
        pendingPermissionResult = result
        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}
