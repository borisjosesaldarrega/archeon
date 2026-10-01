package com.dzknight.archeon.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.webkit.JavascriptInterface;

import org.json.JSONObject;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

final class NativeBridge {
    static final int PERMISSION_REQUEST = 701;
    private static final String SESSION = "session_token";
    private static final String REFRESH = "refresh_token";
    private final MainActivity activity;
    private final SecureStore secureStore;
    private String pendingPermission = "";

    NativeBridge(MainActivity activity, SecureStore secureStore) {
        this.activity = activity;
        this.secureStore = secureStore;
    }

    @JavascriptInterface public String platform() { return "android"; }
    @JavascriptInterface public String deviceName() {
        String custom = secureStore.get("device_name");
        if (custom != null && !custom.isBlank()) return custom;
        String maker = Build.MANUFACTURER == null ? "Android" : Build.MANUFACTURER.trim();
        String model = Build.MODEL == null ? "teléfono" : Build.MODEL.trim();
        if (model.toLowerCase(java.util.Locale.ROOT).startsWith(maker.toLowerCase(java.util.Locale.ROOT))) return model;
        return (maker + " " + model).trim();
    }
    @JavascriptInterface public void setDeviceName(String value) {
        if (value == null) return;
        String clean = value.trim().replaceAll("[\\r\\n\\t]", " ");
        if (clean.isBlank() || clean.length() > 60) return;
        secureStore.put("device_name", clean);
    }
    @JavascriptInterface public String apiBase() { return BuildConfig.ARCHEON_API_BASE_URL; }
    @JavascriptInterface public String publishableKey() { return BuildConfig.ARCHEON_SUPABASE_PUBLISHABLE_KEY; }
    @JavascriptInterface public String installationId() {
        String value = secureStore.get("installation_id");
        if (value == null || value.length() < 16) {
            value = UUID.randomUUID().toString();
            secureStore.put("installation_id", value);
        }
        return value;
    }
    @JavascriptInterface public String getSessionToken() { return secureStore.get(SESSION); }
    @JavascriptInterface public void setSessionToken(String value) {
        if (value == null || value.length() < 16 || value.length() > 8192) return;
        secureStore.put(SESSION, value);
    }
    @JavascriptInterface public void clearSessionToken() { secureStore.remove(SESSION); }
    @JavascriptInterface public String getRefreshToken() { return secureStore.get(REFRESH); }
    @JavascriptInterface public void setRefreshToken(String value) {
        if (value == null || value.length() < 8 || value.length() > 8192) return;
        secureStore.put(REFRESH, value);
    }
    @JavascriptInterface public void clearRefreshToken() { secureStore.remove(REFRESH); }
    @JavascriptInterface public boolean backgroundModeEnabled() {
        return "1".equals(secureStore.get("background_mode"));
    }
    @JavascriptInterface public void setBackgroundModeEnabled(boolean enabled) {
        secureStore.put("background_mode", enabled ? "1" : "0");
        activity.setBackgroundModeEnabled(enabled);
    }
    @JavascriptInterface public void setMediaPlaybackActive(boolean active) {
        activity.setMediaPlaybackActive(active);
    }
    @JavascriptInterface public void playBackgroundAudio(String url, String title, int positionMs) {
        if (url == null || url.isBlank()) return;
        Intent service = new Intent(activity, ArcheonBackgroundService.class)
            .setAction(ArcheonBackgroundService.ACTION_PLAY_AUDIO)
            .putExtra(ArcheonBackgroundService.EXTRA_URL, url)
            .putExtra(ArcheonBackgroundService.EXTRA_TITLE, title == null ? "" : title)
            .putExtra(ArcheonBackgroundService.EXTRA_POSITION_MS, Math.max(0, positionMs));
        activity.startForegroundService(service);
    }
    @JavascriptInterface public String backgroundAudioState() {
        return ArcheonBackgroundService.audioState();
    }
    @JavascriptInterface public void stopBackgroundAudio() {
        Intent service = new Intent(activity, ArcheonBackgroundService.class)
            .setAction(ArcheonBackgroundService.ACTION_STOP_AUDIO);
        activity.startForegroundService(service);
    }

    @JavascriptInterface public String permissionState(String permission) {
        String[] manifest = manifestPermissions(permission);
        if (manifest.length == 0) return "unsupported";
        int grantedCount = 0;
        for (String value : manifest) {
            if (Build.VERSION.SDK_INT < 23 || activity.checkSelfPermission(value) == PackageManager.PERMISSION_GRANTED) grantedCount++;
        }
        if (grantedCount == manifest.length) return "granted";
        if (grantedCount > 0) return "limited";
        boolean rationale = false;
        if (Build.VERSION.SDK_INT >= 23) {
            for (String value : manifest) rationale |= activity.shouldShowRequestPermissionRationale(value);
        }
        boolean asked = "1".equals(secureStore.get("asked_" + permission));
        return rationale ? "denied" : (asked ? "blocked" : "prompt");
    }

    @JavascriptInterface public void requestPermission(String permission) {
        String[] manifest = manifestPermissions(permission);
        if (manifest.length == 0) {
            emitPermission(permission, "unsupported");
            return;
        }
        pendingPermission = permission;
        secureStore.put("asked_" + permission, "1");
        activity.runOnUiThread(() -> activity.requestPermissions(manifest, PERMISSION_REQUEST));
    }

    @JavascriptInterface public void openAppSettings() {
        activity.runOnUiThread(() -> {
            Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            intent.setData(Uri.parse("package:" + activity.getPackageName()));
            activity.startActivity(intent);
        });
    }

    @JavascriptInterface public void notify(String title, String body) {
        activity.showPrivateNotification(title, body);
    }

    @JavascriptInterface public void startSpeech(String mode, String language) {
        activity.startNativeSpeech(mode, language);
    }

    @JavascriptInterface public void stopSpeech() {
        activity.stopNativeSpeech();
    }

    @JavascriptInterface public void speak(String text, String language) {
        activity.speakNative(text, language);
    }

    @JavascriptInterface public boolean ensureAudibleVolume() {
        return activity.ensureAudibleMediaVolume();
    }

    @JavascriptInterface public boolean openApplication(String query) {
        if (query == null || query.isBlank()) return false;
        String key = query.trim().toLowerCase(java.util.Locale.ROOT);
        Map<String, String> known = Map.ofEntries(
            Map.entry("discord", "com.discord"),
            Map.entry("chrome", "com.android.chrome"),
            Map.entry("opera", "com.opera.max.oem"),
            Map.entry("navegador", "com.android.chrome"),
            Map.entry("internet", "com.sec.android.app.sbrowser"),
            Map.entry("youtube", "com.google.android.youtube"),
            Map.entry("spotify", "com.spotify.music"),
            Map.entry("whatsapp", "com.whatsapp"),
            Map.entry("gmail", "com.google.android.gm"),
            Map.entry("maps", "com.google.android.apps.maps")
        );
        String packageName = known.getOrDefault(key, key.contains(".") ? key : "");
        if (packageName.isBlank()) return false;
        Intent launch = activity.getPackageManager().getLaunchIntentForPackage(packageName);
        if (launch == null) return false;
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.runOnUiThread(() -> activity.startActivity(launch));
        return true;
    }

    @JavascriptInterface public boolean saveCloudFile(String name, String mimeType, String contentBase64, boolean preview) {
        if (name == null || name.isBlank() || contentBase64 == null || contentBase64.isBlank()) return false;
        if (contentBase64.length() > 24 * 1024 * 1024) return false;
        String clean = name.trim().replaceAll("[\\\\/\\r\\n\\t]", "_").replace('\u0000', '_');
        if (clean.isBlank() || clean.length() > 255) return false;
        activity.handleCloudFile(clean, mimeType == null ? "application/octet-stream" : mimeType, contentBase64, preview);
        return true;
    }

    String pendingPermission() { return pendingPermission; }
    void clearPendingPermission() { pendingPermission = ""; }

    void emitPermission(String permission, String state) {
        Map<String, String> payload = new LinkedHashMap<>();
        payload.put("permission", permission);
        payload.put("state", state);
        activity.emitNativeEvent("permission", new JSONObject(payload).toString());
    }

    static void createNotificationChannel(Activity activity) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationChannel channel = new NotificationChannel(
            "archeon_private", "ARCHEON", NotificationManager.IMPORTANCE_DEFAULT
        );
        channel.setDescription("Archivos, resultados remotos y avisos de seguridad");
        channel.setLockscreenVisibility(android.app.Notification.VISIBILITY_PRIVATE);
        activity.getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private String[] manifestPermissions(String permission) {
        return switch (permission) {
            case "microphone" -> new String[]{Manifest.permission.RECORD_AUDIO};
            case "camera" -> new String[]{Manifest.permission.CAMERA};
            case "notifications" -> Build.VERSION.SDK_INT >= 33
                ? new String[]{Manifest.permission.POST_NOTIFICATIONS} : new String[]{Manifest.permission.INTERNET};
            case "photos" -> Build.VERSION.SDK_INT >= 33
                ? (Build.VERSION.SDK_INT >= 34
                    ? new String[]{Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO, "android.permission.READ_MEDIA_VISUAL_USER_SELECTED"}
                    : new String[]{Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO})
                : new String[]{Manifest.permission.READ_EXTERNAL_STORAGE};
            case "media" -> Build.VERSION.SDK_INT >= 33
                ? new String[]{Manifest.permission.READ_MEDIA_AUDIO}
                : new String[]{Manifest.permission.READ_EXTERNAL_STORAGE};
            case "bluetooth" -> Build.VERSION.SDK_INT >= 31
                ? new String[]{Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT}
                : new String[0];
            case "local_network" -> new String[]{Manifest.permission.ACCESS_NETWORK_STATE};
            default -> new String[0];
        };
    }
}
