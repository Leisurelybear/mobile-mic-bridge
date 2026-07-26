package com.example.mobile_mic_bridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder

class MicrophoneForegroundService : Service() {
    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Microphone streaming",
                NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java)
                .createNotificationChannel(channel)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val target = intent?.getStringExtra(EXTRA_TARGET).orEmpty()
        val launchIntent = (packageManager.getLaunchIntentForPackage(packageName)
            ?: Intent(this, MainActivity::class.java)).apply {
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val text = if (target.isBlank()) {
            "Streaming microphone"
        } else {
            "Streaming microphone to $target"
        }
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            Notification.Builder(this)
        }
        val notification = builder
            .setContentTitle("Mobile Mic Bridge")
            .setContentText(text)
            .setSmallIcon(applicationInfo.icon)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()
        startForeground(NOTIFICATION_ID, notification)
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val EXTRA_TARGET = "target"
        private const val CHANNEL_ID = "mobile_mic_bridge_microphone"
        private const val NOTIFICATION_ID = 48000
    }
}
