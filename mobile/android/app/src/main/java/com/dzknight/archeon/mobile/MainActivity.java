package com.dzknight.archeon.mobile;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationManager;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import android.view.View;
import android.webkit.ConsoleMessage;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.ProgressBar;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

public final class MainActivity extends Activity {
    private static final int FILE_CHOOSER = 702;
    private WebView webView;
    private View splash;
    private TextView splashStatus;
    private ImageView splashImage;
    private ProgressBar splashProgress;
    private Button splashRetry;
    private boolean mainFrameFailed;
    private NativeBridge bridge;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraCaptureUri;
    private long startedAt;
    private SpeechRecognizer speechRecognizer;
    private String speechMode = "";
    private TextToSpeech textToSpeech;
    private boolean textToSpeechReady;
    private boolean preferredTtsEngine;
    private String textToSpeechEngine = "system";
    private AudioManager audioManager;
    private AudioFocusRequest speechFocusRequest;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        startedAt = System.nanoTime();
        setContentView(R.layout.activity_main);
        webView = findViewById(R.id.web);
        splash = findViewById(R.id.native_splash);
        splashStatus = findViewById(R.id.splash_status);
        splashImage = findViewById(R.id.splash_image);
        splashProgress = findViewById(R.id.splash_progress);
        splashRetry = findViewById(R.id.splash_retry);
        splashRetry.setOnClickListener(view -> loadArcheon());
        bridge = new NativeBridge(this, new SecureStore(this));
        NativeBridge.createNotificationChannel(this);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        audioManager = getSystemService(AudioManager.class);
        initializeTextToSpeech();
        configureWebView();
        handleIntent(getIntent());
        loadArcheon();
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        // ARCHEON only embeds allow-listed media sources. Commands resolve
        // asynchronously, so Android's transient user-gesture token is gone
        // by the time the verified player is ready.
        settings.setMediaPlaybackRequiresUserGesture(false);
        if (BuildConfig.DEBUG) settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.setVerticalScrollBarEnabled(false);
        webView.setHorizontalScrollBarEnabled(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setUserAgentString(settings.getUserAgentString() + " ARCHEON-Mobile/0.1");
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        webView.setBackgroundColor(Color.rgb(5, 9, 12));
        webView.addJavascriptInterface(bridge, "ArcheonNative");
        webView.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme();
                if ("http".equals(scheme) || "https".equals(scheme)) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
                return true;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (mainFrameFailed) return;
                splashStatus.setText("Preparando ARCHI…");
                long elapsed = (System.nanoTime() - startedAt) / 1_000_000L;
                long remaining = Math.max(0L, 450L - elapsed);
                view.postDelayed(() -> {
                    splash.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                    emitNativeEvent("lifecycle", "{\"state\":\"foreground\"}");
                }, remaining);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) {
                    mainFrameFailed = true;
                    webView.setVisibility(View.INVISIBLE);
                    splash.setVisibility(View.VISIBLE);
                    splashImage.setImageResource(R.drawable.archeon_mascot);
                    splashProgress.setVisibility(View.GONE);
                    splashRetry.setVisibility(View.VISIBLE);
                    splashStatus.setText("ARCHEON Mobile no pudo conectar con el servicio. Revisa tu conexión e inténtalo otra vez.");
                }
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    java.util.ArrayList<String> allowed = new java.util.ArrayList<>();
                    for (String resource : request.getResources()) {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)
                            && "granted".equals(bridge.permissionState("microphone"))) allowed.add(resource);
                        if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)
                            && "granted".equals(bridge.permissionState("camera"))) allowed.add(resource);
                    }
                    if (allowed.isEmpty()) request.deny();
                    else request.grant(allowed.toArray(new String[0]));
                });
            }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                if (params.isCaptureEnabled() && acceptsImages(params)) {
                    return openCameraCapture();
                }
                Intent chooser = params.createIntent();
                chooser.addCategory(Intent.CATEGORY_OPENABLE);
                try {
                    startActivityForResult(chooser, FILE_CHOOSER);
                    return true;
                } catch (RuntimeException error) {
                    fileCallback = null;
                    Toast.makeText(MainActivity.this, "No hay selector de archivos disponible", Toast.LENGTH_LONG).show();
                    return false;
                }
            }
            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                return BuildConfig.DEBUG || super.onConsoleMessage(message);
            }
        });
    }

    private boolean acceptsImages(WebChromeClient.FileChooserParams params) {
        String[] types = params.getAcceptTypes();
        if (types == null || types.length == 0) return true;
        for (String type : types) {
            if (type == null || type.isBlank() || type.startsWith("image/") || "*/*".equals(type)) return true;
        }
        return false;
    }

    private boolean openCameraCapture() {
        if (!"granted".equals(bridge.permissionState("camera"))) {
            fileCallback.onReceiveValue(null);
            fileCallback = null;
            bridge.requestPermission("camera");
            Toast.makeText(this, "Permite la cámara y vuelve a tocar Cámara", Toast.LENGTH_LONG).show();
            return true;
        }
        ContentValues values = new ContentValues();
        values.put(MediaStore.Images.Media.DISPLAY_NAME, "ARCHEON_" + System.currentTimeMillis() + ".jpg");
        values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
        if (android.os.Build.VERSION.SDK_INT >= 29) values.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/ARCHEON");
        cameraCaptureUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
        if (cameraCaptureUri == null) {
            fileCallback.onReceiveValue(null);
            fileCallback = null;
            Toast.makeText(this, "No se pudo preparar la cámara", Toast.LENGTH_LONG).show();
            return true;
        }
        Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        camera.putExtra(MediaStore.EXTRA_OUTPUT, cameraCaptureUri);
        camera.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            startActivityForResult(camera, FILE_CHOOSER);
            return true;
        } catch (RuntimeException error) {
            getContentResolver().delete(cameraCaptureUri, null, null);
            cameraCaptureUri = null;
            fileCallback.onReceiveValue(null);
            fileCallback = null;
            Toast.makeText(this, "No hay una cámara disponible", Toast.LENGTH_LONG).show();
            return true;
        }
    }

    private void loadArcheon() {
        String token = BuildConfig.ARCHEON_DEV_TOKEN;
        if (token == null || token.isBlank()) {
            splashStatus.setText("Falta vincular este dispositivo con ARCHEON Desktop");
            return;
        }
        mainFrameFailed = false;
        splash.setVisibility(View.VISIBLE);
        webView.setVisibility(View.INVISIBLE);
        splashImage.setImageResource(R.drawable.archeon_logo);
        splashProgress.setVisibility(View.VISIBLE);
        splashRetry.setVisibility(View.GONE);
        splashStatus.setText("Preparando ARCHI…");
        webView.loadUrl("http://127.0.0.1:56789/mobile.html?token=" + Uri.encode(token));
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else if (webView != null) emitNativeEvent("back", "{}");
        else super.onBackPressed();
    }

    @Override protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
            emitNativeEvent("lifecycle", "{\"state\":\"foreground\"}");
        }
    }

    @Override protected void onPause() {
        if (webView != null) {
            emitNativeEvent("lifecycle", "{\"state\":\"background\"}");
            webView.onPause();
        }
        super.onPause();
    }

    @Override protected void onDestroy() {
        stopNativeSpeech();
        if (speechRecognizer != null) speechRecognizer.destroy();
        speechRecognizer = null;
        if (textToSpeech != null) {
            textToSpeech.stop();
            textToSpeech.shutdown();
        }
        abandonSpeechAudioFocus();
        super.onDestroy();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent == null) return;
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (uri != null) emitNativeEvent("share", new JSONObject(java.util.Map.of("uri", uri.toString())).toString());
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER && fileCallback != null) {
            if (cameraCaptureUri != null) {
                if (resultCode == RESULT_OK) fileCallback.onReceiveValue(new Uri[]{cameraCaptureUri});
                else {
                    getContentResolver().delete(cameraCaptureUri, null, null);
                    fileCallback.onReceiveValue(null);
                }
                cameraCaptureUri = null;
            } else fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != NativeBridge.PERMISSION_REQUEST) return;
        String permission = bridge.pendingPermission();
        String state = bridge.permissionState(permission);
        bridge.emitPermission(permission, state);
        bridge.clearPendingPermission();
    }

    void emitNativeEvent(String name, String json) {
        if (webView == null) return;
        String safeName = JSONObject.quote(name);
        String safeJson = JSONObject.quote(json);
        runOnUiThread(() -> webView.evaluateJavascript(
            "window.dispatchEvent(new CustomEvent('archeon-native',{detail:{type:" + safeName
                + ",payload:JSON.parse(" + safeJson + ")}}));", null
        ));
    }

    void startNativeSpeech(String mode, String language) {
        runOnUiThread(() -> {
            if (!"granted".equals(bridge.permissionState("microphone"))) {
                bridge.requestPermission("microphone");
                return;
            }
            if (!SpeechRecognizer.isRecognitionAvailable(this)) {
                emitSpeech("error", mode, "", "El reconocimiento de voz no está disponible.");
                return;
            }
            cancelSpeechRecognizer();
            speechMode = "wake".equals(mode) ? "wake" : ("conversation".equals(mode) ? "conversation" : "dictation");
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
            speechRecognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params) { emitSpeech("listening", speechMode, "", ""); }
                @Override public void onBeginningOfSpeech() { emitSpeech("listening", speechMode, "", ""); }
                @Override public void onRmsChanged(float rmsdB) { }
                @Override public void onBufferReceived(byte[] buffer) { }
                @Override public void onEndOfSpeech() { emitSpeech("processing", speechMode, "", ""); }
                @Override public void onError(int error) {
                    String message = error == SpeechRecognizer.ERROR_NO_MATCH
                        ? "No entendí lo que dijiste." : "No se pudo reconocer la voz.";
                    emitSpeech(error == SpeechRecognizer.ERROR_CLIENT ? "cancelled" : "error", speechMode, "", message);
                }
                @Override public void onResults(Bundle results) {
                    ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    String text = matches == null || matches.isEmpty() ? "" : matches.get(0);
                    if (text.isBlank()) emitSpeech("error", speechMode, "", "No entendí lo que dijiste.");
                    else emitSpeech("result", speechMode, text, "");
                }
                @Override public void onPartialResults(Bundle partialResults) { }
                @Override public void onEvent(int eventType, Bundle params) { }
            });
            Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
            intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, language == null || language.isBlank() ? Locale.getDefault().toLanguageTag() : language);
            speechRecognizer.startListening(intent);
        });
    }

    void stopNativeSpeech() {
        runOnUiThread(this::cancelSpeechRecognizer);
    }

    private void cancelSpeechRecognizer() {
        if (speechRecognizer == null) return;
        speechRecognizer.cancel();
        speechRecognizer.destroy();
        speechRecognizer = null;
    }

    void speakNative(String text, String language) {
        if (text == null || text.isBlank()) return;
        runOnUiThread(() -> {
            if (!textToSpeechReady || textToSpeech == null) {
                emitSpeech("error", "conversation", "", "La voz de ARCHI no está disponible.");
                return;
            }
            cancelSpeechRecognizer();
            Locale locale = Locale.forLanguageTag(language == null || language.isBlank() ? "es" : language);
            int languageState = textToSpeech.setLanguage(locale);
            if (languageState == TextToSpeech.LANG_MISSING_DATA || languageState == TextToSpeech.LANG_NOT_SUPPORTED) {
                textToSpeech.setLanguage(Locale.getDefault());
            }
            selectBestLocalVoice(locale);
            textToSpeech.setSpeechRate(0.96f);
            textToSpeech.setPitch(1.01f);
            requestSpeechAudioFocus();
            Bundle parameters = new Bundle();
            parameters.putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, 1.0f);
            int result = textToSpeech.speak(text, TextToSpeech.QUEUE_FLUSH, parameters, "archi-mobile-response");
            if (result == TextToSpeech.ERROR) {
                abandonSpeechAudioFocus();
                emitSpeech("error", "conversation", "", "Android no pudo iniciar la voz de ARCHI.");
            }
        });
    }

    private void initializeTextToSpeech() {
        final String preferred = "com.google.android.tts";
        try {
            getPackageManager().getPackageInfo(preferred, 0);
            preferredTtsEngine = true;
            textToSpeechEngine = preferred;
            textToSpeech = new TextToSpeech(this, this::onTextToSpeechInitialized, preferred);
        } catch (PackageManager.NameNotFoundException unavailable) {
            preferredTtsEngine = false;
            textToSpeechEngine = "system";
            textToSpeech = new TextToSpeech(this, this::onTextToSpeechInitialized);
        }
    }

    private void selectBestLocalVoice(Locale requested) {
        if (textToSpeech == null || textToSpeech.getVoices() == null) return;
        Voice best = null;
        int bestScore = Integer.MIN_VALUE;
        for (Voice candidate : textToSpeech.getVoices()) {
            Locale locale = candidate.getLocale();
            if (locale == null || !locale.getLanguage().equalsIgnoreCase(requested.getLanguage())) continue;
            int score = candidate.getQuality() - candidate.getLatency();
            if (!candidate.isNetworkConnectionRequired()) score += 2000;
            if (!requested.getCountry().isBlank() && requested.getCountry().equalsIgnoreCase(locale.getCountry())) score += 400;
            if (candidate.getName().toLowerCase(Locale.ROOT).contains("local")) score += 250;
            if (score > bestScore) { best = candidate; bestScore = score; }
        }
        if (best != null) textToSpeech.setVoice(best);
    }

    private void onTextToSpeechInitialized(int status) {
        runOnUiThread(() -> {
            textToSpeechReady = status == TextToSpeech.SUCCESS && textToSpeech != null;
            if (!textToSpeechReady) {
                if (preferredTtsEngine) {
                    preferredTtsEngine = false;
                    textToSpeechEngine = "system";
                    if (textToSpeech != null) textToSpeech.shutdown();
                    textToSpeech = new TextToSpeech(this, this::onTextToSpeechInitialized);
                    return;
                }
                emitNativeEvent("tts", "{\"state\":\"unavailable\"}");
                return;
            }
            AudioAttributes attributes = new AudioAttributes.Builder()
                // Some Samsung builds route USAGE_ASSISTANT to a muted or
                // unavailable assistant path. ARCHI speech is user-requested
                // foreground audio, so it belongs on the media stream.
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build();
            textToSpeech.setAudioAttributes(attributes);
            textToSpeech.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String utteranceId) {
                    emitNativeEvent("tts", "{\"state\":\"speaking\"}");
                }
                @Override public void onDone(String utteranceId) {
                    abandonSpeechAudioFocus();
                    emitNativeEvent("tts", "{\"state\":\"completed\"}");
                }
                @Override public void onError(String utteranceId) {
                    abandonSpeechAudioFocus();
                    emitNativeEvent("tts", "{\"state\":\"error\"}");
                }
                @Override public void onError(String utteranceId, int errorCode) { onError(utteranceId); }
            });
            emitNativeEvent("tts", new JSONObject(Map.of(
                "state", "ready", "engine", textToSpeechEngine
            )).toString());
        });
    }

    private void requestSpeechAudioFocus() {
        if (audioManager == null) return;
        AudioAttributes attributes = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build();
        speechFocusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attributes)
            .setOnAudioFocusChangeListener(change -> { })
            .build();
        audioManager.requestAudioFocus(speechFocusRequest);
    }

    boolean ensureAudibleMediaVolume() {
        if (audioManager == null) return false;
        int maximum = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        int current = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC);
        boolean muted = audioManager.isStreamMute(AudioManager.STREAM_MUSIC);
        if (current <= 0 || muted) {
            // This method is called only after the user explicitly starts
            // voice conversation or playback. Never alter volume at startup.
            int audible = Math.max(1, Math.round(maximum * 0.35f));
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, audible, 0);
        }
        return audioManager.getStreamVolume(AudioManager.STREAM_MUSIC) > 0
            && !audioManager.isStreamMute(AudioManager.STREAM_MUSIC);
    }

    private void abandonSpeechAudioFocus() {
        if (audioManager != null && speechFocusRequest != null) {
            audioManager.abandonAudioFocusRequest(speechFocusRequest);
            speechFocusRequest = null;
        }
    }

    private void emitSpeech(String state, String mode, String text, String message) {
        Map<String, String> payload = new LinkedHashMap<>();
        payload.put("state", state);
        payload.put("mode", mode == null ? "" : mode);
        payload.put("text", text == null ? "" : text);
        payload.put("message", message == null ? "" : message);
        emitNativeEvent("speech", new JSONObject(payload).toString());
    }

    void showPrivateNotification(String title, String body) {
        runOnUiThread(() -> {
            if (bridge.permissionState("notifications").equals("denied")
                || bridge.permissionState("notifications").equals("prompt")) return;
            Notification notification = new Notification.Builder(this, "archeon_private")
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle(title == null || title.isBlank() ? "ARCHEON" : title)
                .setContentText(body == null ? "Nueva actividad" : body)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setAutoCancel(true)
                .build();
            getSystemService(NotificationManager.class).notify((int) (System.currentTimeMillis() & 0x7fffffff), notification);
        });
    }
}
