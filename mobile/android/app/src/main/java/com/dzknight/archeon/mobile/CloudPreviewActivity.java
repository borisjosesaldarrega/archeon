package com.dzknight.archeon.mobile;

import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import android.util.Log;

import java.io.File;
import java.io.IOException;

public final class CloudPreviewActivity extends Activity {
    private ParcelFileDescriptor descriptor;
    private PdfRenderer renderer;
    private Bitmap bitmap;
    private ImageView image;
    private TextView pageLabel;
    private Button previous;
    private Button next;
    private ProgressBar progress;
    private int pageIndex;
    private float zoom = 1f;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(3, 12, 17));
        getWindow().setNavigationBarColor(Color.rgb(3, 12, 17));
        String path = getIntent().getStringExtra("path");
        String name = getIntent().getStringExtra("name");
        try {
            File previewRoot = new File(getCacheDir(), "cloud-previews").getCanonicalFile();
            File file = path == null ? null : new File(path).getCanonicalFile();
            if (file == null || !file.isFile() || !file.toPath().startsWith(previewRoot.toPath())) {
                throw new IOException("invalid_preview_path");
            }
            descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY);
            renderer = new PdfRenderer(descriptor);
            if (renderer.getPageCount() < 1) throw new IOException("empty_pdf");
            buildInterface(name == null || name.isBlank() ? file.getName() : name);
            renderPage(0);
        } catch (IOException | SecurityException error) {
            Log.e("ArcheonPreview", "Unable to open preview", error);
            Toast.makeText(this, "No se pudo abrir la vista previa.", Toast.LENGTH_LONG).show();
            finish();
        }
    }

    private void buildInterface(String name) {
        int pad = dp(16);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setBackgroundColor(Color.rgb(3, 12, 17));

        TextView title = new TextView(this);
        title.setText(name);
        title.setTextColor(Color.WHITE);
        title.setTextSize(20);
        title.setMaxLines(2);

        pageLabel = new TextView(this);
        pageLabel.setTextColor(Color.rgb(126, 225, 242));
        pageLabel.setTextSize(16);
        pageLabel.setPadding(0, dp(4), 0, dp(10));

        image = new ImageView(this);
        image.setAdjustViewBounds(false);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        image.setBackgroundColor(Color.WHITE);
        image.setContentDescription("Página del documento");

        HorizontalScrollView horizontal = new HorizontalScrollView(this);
        horizontal.setFillViewport(true);
        horizontal.addView(image, new HorizontalScrollView.LayoutParams(
            HorizontalScrollView.LayoutParams.WRAP_CONTENT, HorizontalScrollView.LayoutParams.WRAP_CONTENT));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(false);
        scroll.setBackgroundColor(Color.rgb(20, 27, 31));
        scroll.addView(horizontal, new ScrollView.LayoutParams(
            ScrollView.LayoutParams.MATCH_PARENT, ScrollView.LayoutParams.WRAP_CONTENT));

        progress = new ProgressBar(this);
        progress.setIndeterminate(true);

        LinearLayout navigation = new LinearLayout(this);
        navigation.setOrientation(LinearLayout.HORIZONTAL);
        navigation.setGravity(Gravity.CENTER);
        navigation.setPadding(0, dp(10), 0, 0);

        previous = button("Anterior", view -> renderPage(pageIndex - 1));
        Button zoomOut = button("−", view -> changeZoom(-0.25f));
        Button zoomIn = button("+", view -> changeZoom(0.25f));
        next = button("Siguiente", view -> renderPage(pageIndex + 1));
        Button close = button("Cerrar", view -> finish());

        navigation.addView(previous, weightedButton());
        navigation.addView(zoomOut, weightedButton());
        navigation.addView(zoomIn, weightedButton());
        navigation.addView(next, weightedButton());

        root.addView(title, matchWrap());
        root.addView(pageLabel, matchWrap());
        root.addView(scroll, new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        root.addView(progress, new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(4)));
        root.addView(navigation, matchWrap());
        root.addView(close, matchWrap());
        setContentView(root);
    }

    private Button button(String text, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setOnClickListener(listener);
        return button;
    }

    private LinearLayout.LayoutParams weightedButton() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private void renderPage(int requestedPage) {
        if (renderer == null || requestedPage < 0 || requestedPage >= renderer.getPageCount()) return;
        progress.setVisibility(View.VISIBLE);
        previous.setEnabled(false);
        next.setEnabled(false);
        final int target = requestedPage;
        final float targetZoom = zoom;
        new Thread(() -> {
            Bitmap rendered = null;
            try (PdfRenderer.Page page = renderer.openPage(target)) {
                int available = Math.max(getResources().getDisplayMetrics().widthPixels - dp(32), 640);
                int width = Math.min(Math.round(available * targetZoom), 2400);
                int height = Math.max(1, Math.round(width * (page.getHeight() / (float) page.getWidth())));
                rendered = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
                rendered.eraseColor(Color.WHITE);
                page.render(rendered, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                Bitmap completed = rendered;
                runOnUiThread(() -> applyPage(completed, target));
            } catch (RuntimeException error) {
                if (rendered != null) rendered.recycle();
                runOnUiThread(() -> {
                    progress.setVisibility(View.INVISIBLE);
                    previous.setEnabled(pageIndex > 0);
                    next.setEnabled(renderer != null && pageIndex + 1 < renderer.getPageCount());
                    Toast.makeText(this, "No se pudo mostrar esta página.", Toast.LENGTH_SHORT).show();
                });
            }
        }, "archeon-pdf-page").start();
    }

    private void applyPage(Bitmap rendered, int target) {
        Bitmap old = bitmap;
        bitmap = rendered;
        pageIndex = target;
        ViewGroup.LayoutParams imageLayout = image.getLayoutParams();
        imageLayout.width = rendered.getWidth();
        imageLayout.height = rendered.getHeight();
        image.setLayoutParams(imageLayout);
        image.setImageBitmap(rendered);
        pageLabel.setText("Página " + (pageIndex + 1) + " de " + renderer.getPageCount()
            + " · Zoom " + Math.round(zoom * 100) + "%");
        previous.setEnabled(pageIndex > 0);
        next.setEnabled(pageIndex + 1 < renderer.getPageCount());
        progress.setVisibility(View.INVISIBLE);
        if (old != null && old != rendered && !old.isRecycled()) old.recycle();
    }

    private void changeZoom(float delta) {
        float changed = Math.max(0.75f, Math.min(zoom + delta, 2.5f));
        if (changed == zoom) return;
        zoom = changed;
        renderPage(pageIndex);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override protected void onDestroy() {
        if (bitmap != null && !bitmap.isRecycled()) bitmap.recycle();
        if (renderer != null) renderer.close();
        if (descriptor != null) {
            try { descriptor.close(); } catch (IOException ignored) { }
        }
        super.onDestroy();
    }
}
