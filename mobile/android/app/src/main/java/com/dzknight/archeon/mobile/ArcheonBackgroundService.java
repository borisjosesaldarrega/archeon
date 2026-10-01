package com.dzknight.archeon.mobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.IBinder;
import android.os.PowerManager;

import org.json.JSONObject;

public final class ArcheonBackgroundService extends Service {
    static final String CHANNEL = "archeon_background";
    static final int NOTIFICATION_ID = 4201;
    static final String ACTION_PLAY_AUDIO = "com.dzknight.archeon.mobile.PLAY_AUDIO";
    static final String ACTION_STOP_AUDIO = "com.dzknight.archeon.mobile.STOP_AUDIO";
    static final String EXTRA_URL = "url";
    static final String EXTRA_TITLE = "title";
    static final String EXTRA_POSITION_MS = "position_ms";
    private static final Object PLAYBACK_LOCK = new Object();
    private static MediaPlayer player;
    private static String playingUrl = "";
    private static String playingTitle = "";
    private static boolean preparing;
    private PowerManager.WakeLock playbackWakeLock;

    @Override public void onCreate() {
        super.onCreate();
        NotificationChannel channel = new NotificationChannel(
            CHANNEL, "ARCHEON en segundo plano", NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Mantiene música y activación por voz cuando ARCHEON no está en pantalla");
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (playbackWakeLock == null) {
            PowerManager power = getSystemService(PowerManager.class);
            playbackWakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ARCHEON:background-media");
            playbackWakeLock.setReferenceCounted(false);
        }
        if (!playbackWakeLock.isHeld()) playbackWakeLock.acquire();
        if (intent != null && ACTION_STOP_AUDIO.equals(intent.getAction())) stopNativeAudio();
        if (intent != null && ACTION_PLAY_AUDIO.equals(intent.getAction())) {
            String url = intent.getStringExtra(EXTRA_URL);
            String title = intent.getStringExtra(EXTRA_TITLE);
            int positionMs = Math.max(0, intent.getIntExtra(EXTRA_POSITION_MS, 0));
            if (url != null && !url.isBlank()) playNativeAudio(url, title, positionMs);
        }
        Notification notification = buildNotification();
        startForeground(NOTIFICATION_ID, notification);
        return START_STICKY;
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(
            this, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        String title;
        synchronized (PLAYBACK_LOCK) { title = playingTitle; }
        return new Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.archeon_orb)
            .setContentTitle(title == null || title.isBlank() ? "ARCHEON activo" : title)
            .setContentText(title == null || title.isBlank()
                ? "Activación por voz disponible en segundo plano"
                : "Reproduciendo en segundo plano")
            .setContentIntent(pending)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build();
    }

    private void playNativeAudio(String url, String title, int positionMs) {
        stopNativeAudio();
        MediaPlayer next = new MediaPlayer();
        next.setAudioAttributes(new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build());
        next.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
        synchronized (PLAYBACK_LOCK) {
            player = next;
            playingUrl = url;
            playingTitle = title == null ? "" : title.trim();
            preparing = true;
        }
        next.setOnPreparedListener(value -> {
            synchronized (PLAYBACK_LOCK) {
                if (player != value) return;
                preparing = false;
                if (positionMs > 0) value.seekTo(positionMs);
                value.start();
            }
            getSystemService(NotificationManager.class).notify(NOTIFICATION_ID, buildNotification());
        });
        next.setOnCompletionListener(value -> stopNativeAudio());
        next.setOnErrorListener((value, what, extra) -> {
            stopNativeAudio();
            return true;
        });
        try {
            next.setDataSource(this, Uri.parse(url));
            next.prepareAsync();
        } catch (Exception error) {
            stopNativeAudio();
        }
    }

    private static void stopNativeAudio() {
        synchronized (PLAYBACK_LOCK) {
            if (player != null) {
                try { player.stop(); } catch (IllegalStateException ignored) { }
                player.reset();
                player.release();
            }
            player = null;
            playingUrl = "";
            playingTitle = "";
            preparing = false;
        }
    }

    static String audioState() {
        JSONObject state = new JSONObject();
        synchronized (PLAYBACK_LOCK) {
            int position = 0;
            boolean active = player != null;
            boolean playing = false;
            if (player != null && !preparing) {
                try {
                    position = player.getCurrentPosition();
                    playing = player.isPlaying();
                } catch (IllegalStateException ignored) { }
            }
            try {
                state.put("active", active);
                state.put("playing", playing || preparing);
                state.put("position_ms", position);
                state.put("url", playingUrl);
            } catch (Exception ignored) { }
        }
        return state.toString();
    }

    @Override public void onDestroy() {
        stopNativeAudio();
        if (playbackWakeLock != null && playbackWakeLock.isHeld()) playbackWakeLock.release();
        playbackWakeLock = null;
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
