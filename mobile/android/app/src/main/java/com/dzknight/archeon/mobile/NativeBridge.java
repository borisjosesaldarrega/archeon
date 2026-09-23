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

final class NativeBridge {
    static final int PERMISSION_REQUEST = 701;
    private static final String SESSION = "session_token";
    private final MainActivity activity;
    private final SecureStore secureStore;
    private String pendingPermission = "";

    NativeBridge(MainActivity activity, SecureStore secureStore) {
        this.activity = activity;
        this.secureStore = secureStore;
    }

    @JavascriptInterface public String platform() { return "android"; }
    @JavascriptInterface public String getSessionToken() { return secureStore.get(SESSION); }
    @JavascriptInterface public void setSessionToken(String value) {
        if (value == null || value.length() < 16 || value.length() > 8192) return;
        secureStore.put(SESSION, value);
    }
    @JavascriptInterface public void clearSessionToken() { secureStore.remove(SESSION); }

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
