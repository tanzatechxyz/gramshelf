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

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private ApiClient api;
    private LinearLayout content;
    private ProgressBar loading;
    private int itemId;
    private int requestGeneration;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Ui.GREEN_DARK);
        getWindow().setNavigationBarColor(Ui.PAPER);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);

        itemId = getIntent().getIntExtra(EXTRA_ITEM_ID, -1);
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
        back.setText(R.string.back);
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
        toolbar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        screen.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1
        ));

        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(Ui.dp(this, 16), Ui.dp(this, 18), Ui.dp(this, 16), Ui.dp(this, 32));
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        loading = new ProgressBar(this);
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(
                Ui.dp(this, 48),
                Ui.dp(this, 48)
        );
        progressParams.gravity = Gravity.CENTER_HORIZONTAL;
        progressParams.setMargins(0, Ui.dp(this, 48), 0, 0);
        content.addView(loading, progressParams);

        setContentView(screen);
    }

    private void loadItem() {
        content.removeAllViews();
        content.addView(loading);
        loading.setVisibility(View.VISIBLE);
        int generation = ++requestGeneration;
        executor.execute(() -> {
            try {
                Models.ItemDetail item = api.item(itemId);
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

        LinearLayout summary = Ui.card(this);
        content.addView(summary);

        LinearLayout heading = new LinearLayout(this);
        heading.setOrientation(LinearLayout.HORIZONTAL);
        heading.setGravity(Gravity.CENTER_VERTICAL);
        summary.addView(heading, matchWrap());

        TextView author = Ui.heading(this, "@" + item.author, 22);
        author.setSingleLine(true);
        heading.addView(author, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        heading.addView(Ui.badge(this, item.mediaType), wrapWrap());

        if (!item.caption.isBlank()) {
            TextView caption = Ui.text(this, item.caption, 16, Ui.INK);
            caption.setTextIsSelectable(true);
            LinearLayout.LayoutParams captionParams = matchWrap();
            captionParams.setMargins(0, Ui.dp(this, 14), 0, 0);
            summary.addView(caption, captionParams);
        }

        TextView dates = Ui.text(
                this,
                "Published " + Ui.displayDate(item.publishedAt)
                        + " · Saved " + Ui.displayDate(item.downloadedAt),
                12,
                Ui.MUTED
        );
        LinearLayout.LayoutParams dateParams = matchWrap();
        dateParams.setMargins(0, Ui.dp(this, 14), 0, Ui.dp(this, 10));
        summary.addView(dates, dateParams);

        Button instagram = Ui.secondaryButton(this, "Open original on Instagram");
        summary.addView(instagram, matchWrap());
        instagram.setOnClickListener(view -> openInstagram(item.instagramUrl));

        TextView mediaHeading = Ui.heading(
                this,
                item.media.size() == 1 ? "Media" : "Media · " + item.media.size(),
                20
        );
        LinearLayout.LayoutParams mediaHeadingParams = matchWrap();
        mediaHeadingParams.setMargins(Ui.dp(this, 2), Ui.dp(this, 4), 0, Ui.dp(this, 12));
        content.addView(mediaHeading, mediaHeadingParams);

        if (item.media.isEmpty()) {
            TextView empty = Ui.text(this, "No downloaded media is available.", 15, Ui.MUTED);
            content.addView(empty, matchWrap());
            return;
        }

        for (Models.Media media : item.media) {
            content.addView(mediaCard(media, item.media.size()));
        }
    }

    private View mediaCard(Models.Media media, int total) {
        LinearLayout card = Ui.card(this);

        TextView label = Ui.text(
                this,
                total > 1 ? media.kind + " · " + (media.position + 1) + " of " + total : media.kind,
                12,
                Ui.MUTED
        );
        label.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        LinearLayout.LayoutParams labelParams = matchWrap();
        labelParams.setMargins(0, 0, 0, Ui.dp(this, 10));
        card.addView(label, labelParams);

        if (media.kind.equals("video")) {
            card.addView(videoPlayer(media), matchWrap());
        } else {
            FrameLayout frame = new FrameLayout(this);
            frame.setBackground(Ui.roundRect(Ui.SAND, 12, 0, Color.TRANSPARENT, this));
            card.addView(frame, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    Ui.dp(this, 340)
            ));

            ImageView image = new ImageView(this);
            image.setScaleType(ImageView.ScaleType.FIT_CENTER);
            image.setContentDescription("Archived image " + (media.position + 1));
            frame.addView(image, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
            ));

            ProgressBar progress = new ProgressBar(this);
            frame.addView(progress, new FrameLayout.LayoutParams(
                    Ui.dp(this, 42),
                    Ui.dp(this, 42),
                    Gravity.CENTER
            ));
            ImageLoader.load(image, progress, media.url, api);
        }
        return card;
    }

    private View videoPlayer(Models.Media media) {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);

        FrameLayout videoFrame = new FrameLayout(this);
        videoFrame.setBackgroundColor(Color.BLACK);
        container.addView(videoFrame, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                Ui.dp(this, 260)
        ));

        VideoView video = new VideoView(this);
        video.setVisibility(View.GONE);
        videoFrame.addView(video, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        Button play = Ui.primaryButton(this, "Play video");
        FrameLayout.LayoutParams playParams = new FrameLayout.LayoutParams(
                Ui.dp(this, 170),
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER
        );
        videoFrame.addView(play, playParams);

        ProgressBar preparing = new ProgressBar(this);
        preparing.setVisibility(View.GONE);
        videoFrame.addView(preparing, new FrameLayout.LayoutParams(
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
                    video.start();
                });
                video.setOnErrorListener((player, what, extra) -> {
                    preparing.setVisibility(View.GONE);
                    play.setVisibility(View.VISIBLE);
                    Toast.makeText(this, "This video could not be played.", Toast.LENGTH_LONG).show();
                    return true;
                });
            } catch (RuntimeException exception) {
                preparing.setVisibility(View.GONE);
                play.setVisibility(View.VISIBLE);
                Toast.makeText(this, ApiClient.friendlyError(exception), Toast.LENGTH_LONG).show();
            }
        });
        return container;
    }

    private void renderError(String error) {
        content.removeAllViews();
        LinearLayout card = Ui.card(this);
        content.addView(card);

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

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    private LinearLayout.LayoutParams wrapWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    @Override
    protected void onDestroy() {
        requestGeneration++;
        executor.shutdownNow();
        super.onDestroy();
    }
}
