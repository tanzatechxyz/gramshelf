package xyz.tanzatech.gramshelf;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.MediaController;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.VideoView;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class DetailActivity extends Activity {
    public static final String EXTRA_ITEM_ID = "item_id";
    private static final String STATE_ITEM_ID = "current_item_id";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private ApiClient api;
    private ScrollView scroll;
    private LinearLayout content;
    private int itemId;
    private int requestGeneration;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Ui.GREEN_DARK);
        getWindow().setNavigationBarColor(Ui.PAPER);
        getWindow().getDecorView().setSystemUiVisibility(0);

        itemId = savedInstanceState == null
                ? getIntent().getIntExtra(EXTRA_ITEM_ID, -1)
                : savedInstanceState.getInt(STATE_ITEM_ID, -1);
        ConfigStore config = new ConfigStore(this);
        if (itemId < 0 || !config.isConfigured()) {
            finish();
            return;
        }
        try {
            api = new ApiClient(config.server(), config.token());
        } catch (IllegalArgumentException exception) {
            finish();
            return;
        }

        buildScreen();
        loadItem();
    }

    private void buildScreen() {
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setBackgroundColor(Ui.PAPER);
        screen.setFitsSystemWindows(true);

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(Ui.dp(this, 8), Ui.dp(this, 8), Ui.dp(this, 16), Ui.dp(this, 8));
        toolbar.setBackgroundColor(Ui.GREEN_DARK);
        screen.addView(toolbar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                Ui.dp(this, 64)
        ));

        Button back = new Button(this);
        back.setText("← Shelf");
        back.setAllCaps(false);
        back.setTextColor(Ui.WHITE);
        back.setTextSize(15);
        back.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Ui.GREEN_DARK));
        toolbar.addView(back, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        back.setOnClickListener(view -> finish());

        TextView title = Ui.text(this, "Archived post", 20, Ui.WHITE);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setGravity(Gravity.END);
        toolbar.addView(title, new LinearLayout.LayoutParams(
                0,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                1
        ));

        scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Ui.PAPER);
        screen.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1
        ));

        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(0, 0, 0, Ui.dp(this, 24));
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        setContentView(screen);
    }

    private void loadItem() {
        content.removeAllViews();
        scroll.scrollTo(0, 0);

        ProgressBar loading = new ProgressBar(this);
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(
                Ui.dp(this, 48),
                Ui.dp(this, 48)
        );
        progressParams.gravity = Gravity.CENTER_HORIZONTAL;
        progressParams.setMargins(0, Ui.dp(this, 48), 0, 0);
        content.addView(loading, progressParams);

        int requestedItemId = itemId;
        int generation = ++requestGeneration;
        executor.execute(() -> {
            try {
                Models.ItemDetail item = api.item(requestedItemId);
                runOnUiThread(() -> {
                    if (generation != requestGeneration || isFinishing()) {
                        return;
                    }
                    render(item);
                });
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    if (generation != requestGeneration || isFinishing()) {
                        return;
                    }
                    renderError(ApiClient.friendlyError(exception));
                });
            }
        });
    }

    private void render(Models.ItemDetail item) {
        content.removeAllViews();

        if (item.media.isEmpty()) {
            LinearLayout emptyCard = Ui.card(this);
            TextView empty = Ui.text(this, "No downloaded media is available.", 15, Ui.MUTED);
            emptyCard.addView(empty, matchWrap());
            content.addView(emptyCard, insetCardParams());
        } else {
            for (Models.Media media : item.media) {
                content.addView(mediaPanel(media, item.media.size()));
            }
        }

        content.addView(infoPanel(item), insetCardParams());
    }

    private View mediaPanel(Models.Media media, int total) {
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(Color.BLACK);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                maximumMediaHeight()
        );
        params.setMargins(0, 0, 0, Ui.dp(this, 10));
        frame.setLayoutParams(params);

        if (media.kind.equals("video")) {
            addVideoPlayer(frame, media);
        } else {
            ImageView image = new ImageView(this);
            image.setScaleType(ImageView.ScaleType.FIT_CENTER);
            image.setContentDescription("Archived image " + (media.position + 1));
            frame.addView(image, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    Gravity.CENTER
            ));

            ProgressBar progress = new ProgressBar(this);
            frame.addView(progress, new FrameLayout.LayoutParams(
                    Ui.dp(this, 42),
                    Ui.dp(this, 42),
                    Gravity.CENTER
            ));
            ImageLoader.load(image, progress, media.url, api);
        }

        if (total > 1) {
            TextView label = Ui.text(
                    this,
                    (media.position + 1) + " of " + total,
                    12,
                    Ui.WHITE
            );
            label.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            label.setGravity(Gravity.CENTER);
            label.setPadding(
                    Ui.dp(this, 10),
                    Ui.dp(this, 6),
                    Ui.dp(this, 10),
                    Ui.dp(this, 6)
            );
            label.setBackground(Ui.roundRect(
                    Color.argb(220, 20, 24, 21),
                    999,
                    0,
                    Color.TRANSPARENT,
                    this
            ));
            FrameLayout.LayoutParams labelParams = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.TOP | Gravity.START
            );
            labelParams.setMargins(Ui.dp(this, 12), Ui.dp(this, 12), 0, 0);
            frame.addView(label, labelParams);
        }

        return frame;
    }

    private void addVideoPlayer(FrameLayout frame, Models.Media media) {
        VideoView video = new VideoView(this);
        video.setVisibility(View.GONE);
        frame.addView(video, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
                Gravity.CENTER
        ));

        Button play = Ui.primaryButton(this, "Play video");
        FrameLayout.LayoutParams playParams = new FrameLayout.LayoutParams(
                Ui.dp(this, 170),
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER
        );
        frame.addView(play, playParams);

        ProgressBar preparing = new ProgressBar(this);
        preparing.setVisibility(View.GONE);
        frame.addView(preparing, new FrameLayout.LayoutParams(
                Ui.dp(this, 44),
                Ui.dp(this, 44),
                Gravity.CENTER
        ));

        play.setOnClickListener(view -> {
            try {
                play.setVisibility(View.GONE);
                preparing.setVisibility(View.VISIBLE);
                video.setVisibility(View.VISIBLE);
                MediaController controls = new MediaController(this);
                controls.setAnchorView(video);
                video.setMediaController(controls);
                video.setVideoURI(Uri.parse(media.url), api.mediaHeaders(media.url));
                video.setOnPreparedListener(player -> {
                    preparing.setVisibility(View.GONE);
                    player.setLooping(false);
                    fitVideoToFrame(frame, video, player.getVideoWidth(), player.getVideoHeight());
                    video.start();
                    controls.show();
                });
                video.setOnErrorListener((player, what, extra) -> {
                    preparing.setVisibility(View.GONE);
                    video.setVisibility(View.GONE);
                    play.setVisibility(View.VISIBLE);
                    Toast.makeText(this, "This video could not be played.", Toast.LENGTH_LONG).show();
                    return true;
                });
            } catch (RuntimeException exception) {
                preparing.setVisibility(View.GONE);
                video.setVisibility(View.GONE);
                play.setVisibility(View.VISIBLE);
                Toast.makeText(this, ApiClient.friendlyError(exception), Toast.LENGTH_LONG).show();
            }
        });
    }

    private void fitVideoToFrame(FrameLayout frame, VideoView video, int width, int height) {
        if (width <= 0 || height <= 0) {
            return;
        }
        frame.post(() -> {
            int availableWidth = frame.getWidth();
            int availableHeight = frame.getHeight();
            if (availableWidth <= 0 || availableHeight <= 0) {
                return;
            }
            float scale = Math.min(
                    (float) availableWidth / width,
                    (float) availableHeight / height
            );
            FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                    Math.max(1, Math.round(width * scale)),
                    Math.max(1, Math.round(height * scale)),
                    Gravity.CENTER
            );
            video.setLayoutParams(params);
        });
    }

    private LinearLayout infoPanel(Models.ItemDetail item) {
        LinearLayout panel = Ui.card(this);

        TextView eyebrow = Ui.text(
                this,
                item.mediaType + " · " + item.media.size()
                        + (item.media.size() == 1 ? " file" : " files"),
                12,
                Ui.GREEN_SOFT
        );
        eyebrow.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        panel.addView(eyebrow, matchWrap());

        TextView author = Ui.heading(this, "@" + item.author, 25);
        LinearLayout.LayoutParams authorParams = matchWrap();
        authorParams.setMargins(0, Ui.dp(this, 6), 0, Ui.dp(this, 4));
        panel.addView(author, authorParams);

        TextView published = Ui.text(
                this,
                "Published " + Ui.displayDate(item.publishedAt),
                13,
                Ui.MUTED
        );
        panel.addView(published, matchWrap());

        View divider = new View(this);
        divider.setBackgroundColor(Ui.BORDER);
        LinearLayout.LayoutParams dividerParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                Ui.dp(this, 1)
        );
        dividerParams.setMargins(0, Ui.dp(this, 18), 0, Ui.dp(this, 18));
        panel.addView(divider, dividerParams);

        TextView captionHeading = Ui.heading(this, "Caption", 19);
        panel.addView(captionHeading, matchWrap());

        TextView caption = Ui.text(
                this,
                item.caption.isBlank() ? "No caption was available." : item.caption,
                16,
                item.caption.isBlank() ? Ui.MUTED : Ui.INK
        );
        caption.setTextIsSelectable(true);
        LinearLayout.LayoutParams captionParams = matchWrap();
        captionParams.setMargins(0, Ui.dp(this, 10), 0, Ui.dp(this, 18));
        panel.addView(caption, captionParams);

        addMetadataRow(panel, "Shortcode", item.shortcode);
        addMetadataRow(panel, "Downloaded", Ui.displayDate(item.downloadedAt));
        addMetadataRow(panel, "Original URL", item.instagramUrl);

        Button instagram = Ui.primaryButton(this, "View on Instagram");
        LinearLayout.LayoutParams instagramParams = matchWrap();
        instagramParams.setMargins(0, Ui.dp(this, 16), 0, Ui.dp(this, 10));
        panel.addView(instagram, instagramParams);
        instagram.setOnClickListener(view -> openInstagram(item.instagramUrl));

        LinearLayout navigation = new LinearLayout(this);
        navigation.setOrientation(LinearLayout.HORIZONTAL);
        navigation.setGravity(Gravity.CENTER_VERTICAL);
        panel.addView(navigation, matchWrap());

        Button previous = Ui.secondaryButton(this, "← Previous");
        previous.setEnabled(item.previousItemId != null);
        previous.setAlpha(item.previousItemId == null ? 0.45f : 1f);
        navigation.addView(previous, new LinearLayout.LayoutParams(
                0,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                1
        ));
        previous.setOnClickListener(view -> navigateTo(item.previousItemId));

        Button next = Ui.secondaryButton(this, "Next →");
        next.setEnabled(item.nextItemId != null);
        next.setAlpha(item.nextItemId == null ? 0.45f : 1f);
        LinearLayout.LayoutParams nextParams = new LinearLayout.LayoutParams(
                0,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                1
        );
        nextParams.setMargins(Ui.dp(this, 8), 0, 0, 0);
        navigation.addView(next, nextParams);
        next.setOnClickListener(view -> navigateTo(item.nextItemId));

        return panel;
    }

    private void addMetadataRow(LinearLayout panel, String label, String value) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.TOP);
        LinearLayout.LayoutParams rowParams = matchWrap();
        rowParams.setMargins(0, 0, 0, Ui.dp(this, 10));
        panel.addView(row, rowParams);

        TextView name = Ui.text(this, label, 13, Ui.MUTED);
        name.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        row.addView(name, new LinearLayout.LayoutParams(
                0,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                0.34f
        ));

        TextView detail = Ui.text(this, value, 13, Ui.INK);
        detail.setTextIsSelectable(true);
        row.addView(detail, new LinearLayout.LayoutParams(
                0,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                0.66f
        ));
    }

    private int maximumMediaHeight() {
        int screenHeight = getResources().getDisplayMetrics().heightPixels;
        return Math.max(Ui.dp(this, 240), screenHeight - Ui.dp(this, 112));
    }

    private void navigateTo(Integer targetItemId) {
        if (targetItemId == null) {
            return;
        }
        itemId = targetItemId;
        loadItem();
    }

    private void renderError(String error) {
        content.removeAllViews();
        LinearLayout card = Ui.card(this);
        content.addView(card, insetCardParams());

        TextView title = Ui.heading(this, "Could not open this post", 20);
        card.addView(title, matchWrap());

        TextView detail = Ui.text(this, error, 15, Ui.ERROR);
        LinearLayout.LayoutParams detailParams = matchWrap();
        detailParams.setMargins(0, Ui.dp(this, 10), 0, Ui.dp(this, 16));
        card.addView(detail, detailParams);

        Button retry = Ui.primaryButton(this, "Try again");
        card.addView(retry, matchWrap());
        retry.setOnClickListener(view -> loadItem());
    }

    private void openInstagram(String url) {
        Uri uri = Uri.parse(url);
        if (!"https".equalsIgnoreCase(uri.getScheme())) {
            Toast.makeText(this, "The saved Instagram URL is invalid.", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (RuntimeException exception) {
            Toast.makeText(this, "No browser can open this link.", Toast.LENGTH_LONG).show();
        }
    }

    private LinearLayout.LayoutParams insetCardParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(
                Ui.dp(this, 16),
                Ui.dp(this, 6),
                Ui.dp(this, 16),
                Ui.dp(this, 14)
        );
        return params;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        outState.putInt(STATE_ITEM_ID, itemId);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        requestGeneration++;
        executor.shutdownNow();
        super.onDestroy();
    }
}
