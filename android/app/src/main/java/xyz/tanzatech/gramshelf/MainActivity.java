package xyz.tanzatech.gramshelf;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PAGE_SIZE = 20;
    private static final String[] FILTER_LABELS = {"All media", "Images", "Videos", "Carousels"};
    private static final String[] FILTER_VALUES = {"", "image", "video", "carousel"};

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private ConfigStore config;
    private ApiClient api;

    private EditText queryInput;
    private Spinner typeSpinner;
    private LinearLayout itemList;
    private ProgressBar progress;
    private TextView message;
    private TextView statusText;
    private Button refreshButton;
    private Button syncButton;
    private Button searchButton;
    private Button loadMoreButton;

    private String activeQuery = "";
    private String activeType = "";
    private int nextOffset;
    private int requestGeneration;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Ui.GREEN_DARK);
        getWindow().setNavigationBarColor(Ui.PAPER);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        config = new ConfigStore(this);
        if (config.isConfigured()) {
            openConfiguredShelf();
        } else {
            showConnection(false);
        }
    }

    private void openConfiguredShelf() {
        try {
            api = new ApiClient(config.server(), config.token());
            showShelf();
        } catch (IllegalArgumentException exception) {
            showConnection(false);
        }
    }

    private void showConnection(boolean allowCancel) {
        requestGeneration++;
        api = null;

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Ui.PAPER);
        scroll.setFitsSystemWindows(true);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        content.setPadding(Ui.dp(this, 24), Ui.dp(this, 48), Ui.dp(this, 24), Ui.dp(this, 32));
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        TextView mark = Ui.text(this, "GS", 24, Ui.WHITE);
        mark.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        mark.setGravity(Gravity.CENTER);
        mark.setBackground(Ui.roundRect(Ui.GREEN, 22, 0, Color.TRANSPARENT, this));
        content.addView(mark, new LinearLayout.LayoutParams(Ui.dp(this, 72), Ui.dp(this, 72)));

        TextView title = Ui.heading(this, "Your saved posts, on your phone", 27);
        title.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams titleParams = matchWrap();
        titleParams.setMargins(0, Ui.dp(this, 24), 0, Ui.dp(this, 8));
        content.addView(title, titleParams);

        TextView intro = Ui.text(
                this,
                "Connect directly to your self-hosted GramShelf server.",
                16,
                Ui.MUTED
        );
        intro.setGravity(Gravity.CENTER);
        content.addView(intro, matchWrap());

        LinearLayout form = Ui.card(this);
        LinearLayout.LayoutParams formParams = matchWrap();
        formParams.setMargins(0, Ui.dp(this, 32), 0, 0);
        form.setLayoutParams(formParams);
        content.addView(form);

        TextView serverLabel = Ui.heading(this, "Server address", 14);
        form.addView(serverLabel, matchWrap());

        EditText serverInput = new EditText(this);
        serverInput.setHint("http://192.168.1.20:8080");
        serverInput.setSingleLine(true);
        serverInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        serverInput.setText(config.server());
        serverInput.setSelectAllOnFocus(false);
        LinearLayout.LayoutParams inputParams = matchWrap();
        inputParams.setMargins(0, Ui.dp(this, 4), 0, Ui.dp(this, 18));
        form.addView(serverInput, inputParams);

        TextView tokenLabel = Ui.heading(this, "API token", 14);
        form.addView(tokenLabel, matchWrap());

        EditText tokenInput = new EditText(this);
        tokenInput.setHint("gs_…");
        tokenInput.setSingleLine(true);
        tokenInput.setInputType(
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                        | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        );
        tokenInput.setText(config.token());
        LinearLayout.LayoutParams tokenParams = matchWrap();
        tokenParams.setMargins(0, Ui.dp(this, 4), 0, Ui.dp(this, 8));
        form.addView(tokenInput, tokenParams);

        TextView tokenHelp = Ui.text(
                this,
                "Copy the token from GramShelf → Settings → API.",
                13,
                Ui.MUTED
        );
        form.addView(tokenHelp, matchWrap());

        TextView connectionError = Ui.text(this, "", 14, Ui.ERROR);
        connectionError.setVisibility(View.GONE);
        LinearLayout.LayoutParams errorParams = matchWrap();
        errorParams.setMargins(0, Ui.dp(this, 14), 0, 0);
        form.addView(connectionError, errorParams);

        Button connect = Ui.primaryButton(this, "Connect to GramShelf");
        LinearLayout.LayoutParams connectParams = matchWrap();
        connectParams.setMargins(0, Ui.dp(this, 18), 0, 0);
        form.addView(connect, connectParams);

        if (allowCancel && config.isConfigured()) {
            Button cancel = Ui.secondaryButton(this, "Cancel");
            LinearLayout.LayoutParams cancelParams = matchWrap();
            cancelParams.setMargins(0, Ui.dp(this, 8), 0, 0);
            form.addView(cancel, cancelParams);
            cancel.setOnClickListener(view -> openConfiguredShelf());
        }

        TextView security = Ui.text(
                this,
                "The token stays in this app's private storage. Use HTTPS outside a trusted home network.",
                13,
                Ui.MUTED
        );
        security.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams securityParams = matchWrap();
        securityParams.setMargins(0, Ui.dp(this, 14), 0, 0);
        content.addView(security, securityParams);

        connect.setOnClickListener(view -> {
            connectionError.setVisibility(View.GONE);
            String normalized;
            ApiClient candidate;
            try {
                normalized = ApiClient.normalizeBaseUrl(serverInput.getText().toString());
                candidate = new ApiClient(normalized, tokenInput.getText().toString());
            } catch (IllegalArgumentException exception) {
                showInlineError(connectionError, exception.getMessage());
                return;
            }

            connect.setEnabled(false);
            connect.setText(R.string.connecting);
            int generation = ++requestGeneration;
            executor.execute(() -> {
                try {
                    candidate.status();
                    runOnUiThread(() -> {
                        if (generation != requestGeneration || isFinishing()) {
                            return;
                        }
                        config.save(normalized, tokenInput.getText().toString().trim());
                        api = candidate;
                        showShelf();
                    });
                } catch (Exception exception) {
                    runOnUiThread(() -> {
                        if (generation != requestGeneration || isFinishing()) {
                            return;
                        }
                        connect.setEnabled(true);
                        connect.setText(R.string.connect);
                        showInlineError(connectionError, ApiClient.friendlyError(exception));
                    });
                }
            });
        });

        setContentView(scroll);
    }

    private void showShelf() {
        requestGeneration++;
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setBackgroundColor(Ui.PAPER);
        screen.setFitsSystemWindows(true);

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(Ui.dp(this, 18), Ui.dp(this, 10), Ui.dp(this, 10), Ui.dp(this, 10));
        toolbar.setBackgroundColor(Ui.GREEN_DARK);
        screen.addView(toolbar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                Ui.dp(this, 64)
        ));

        TextView title = Ui.text(this, "GramShelf", 22, Ui.WHITE);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        Button connection = toolbarButton("Connection");
        toolbar.addView(connection, wrapWrap());
        connection.setOnClickListener(view -> showConnection(true));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        screen.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1
        ));

        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(Ui.dp(this, 16), Ui.dp(this, 16), Ui.dp(this, 16), Ui.dp(this, 32));
        scroll.addView(body, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        LinearLayout statusCard = Ui.card(this);
        body.addView(statusCard);
        TextView statusHeading = Ui.heading(this, "Archive", 18);
        statusCard.addView(statusHeading, matchWrap());

        statusText = Ui.text(this, "Checking your server…", 14, Ui.MUTED);
        LinearLayout.LayoutParams statusParams = matchWrap();
        statusParams.setMargins(0, Ui.dp(this, 5), 0, Ui.dp(this, 12));
        statusCard.addView(statusText, statusParams);

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        statusCard.addView(actions, matchWrap());

        refreshButton = Ui.secondaryButton(this, "Refresh");
        actions.addView(refreshButton, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        syncButton = Ui.primaryButton(this, "Sync now");
        LinearLayout.LayoutParams syncParams = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        syncParams.setMargins(Ui.dp(this, 8), 0, 0, 0);
        actions.addView(syncButton, syncParams);

        LinearLayout searchCard = Ui.card(this);
        body.addView(searchCard);
        TextView searchHeading = Ui.heading(this, "Find in your archive", 17);
        searchCard.addView(searchHeading, matchWrap());

        queryInput = new EditText(this);
        queryInput.setHint("Caption, author, or shortcode");
        queryInput.setSingleLine(true);
        queryInput.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        LinearLayout.LayoutParams queryParams = matchWrap();
        queryParams.setMargins(0, Ui.dp(this, 5), 0, Ui.dp(this, 8));
        searchCard.addView(queryInput, queryParams);

        LinearLayout filterRow = new LinearLayout(this);
        filterRow.setOrientation(LinearLayout.HORIZONTAL);
        filterRow.setGravity(Gravity.CENTER_VERTICAL);
        searchCard.addView(filterRow, matchWrap());

        typeSpinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(
                this,
                android.R.layout.simple_spinner_dropdown_item,
                FILTER_LABELS
        );
        typeSpinner.setAdapter(adapter);
        filterRow.addView(typeSpinner, new LinearLayout.LayoutParams(0, Ui.dp(this, 48), 1));

        searchButton = Ui.primaryButton(this, "Search");
        LinearLayout.LayoutParams searchParams = new LinearLayout.LayoutParams(
                Ui.dp(this, 112),
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
        searchParams.setMargins(Ui.dp(this, 8), 0, 0, 0);
        filterRow.addView(searchButton, searchParams);

        TextView timelineHeading = Ui.heading(this, "Newest downloads", 21);
        LinearLayout.LayoutParams timelineParams = matchWrap();
        timelineParams.setMargins(Ui.dp(this, 2), Ui.dp(this, 4), 0, Ui.dp(this, 12));
        body.addView(timelineHeading, timelineParams);

        progress = new ProgressBar(this);
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(
                Ui.dp(this, 42),
                Ui.dp(this, 42)
        );
        progressParams.gravity = Gravity.CENTER_HORIZONTAL;
        progressParams.setMargins(0, Ui.dp(this, 10), 0, Ui.dp(this, 12));
        body.addView(progress, progressParams);

        message = Ui.text(this, "", 15, Ui.MUTED);
        message.setGravity(Gravity.CENTER);
        message.setVisibility(View.GONE);
        LinearLayout.LayoutParams messageParams = matchWrap();
        messageParams.setMargins(0, Ui.dp(this, 12), 0, Ui.dp(this, 18));
        body.addView(message, messageParams);

        itemList = new LinearLayout(this);
        itemList.setOrientation(LinearLayout.VERTICAL);
        body.addView(itemList, matchWrap());

        loadMoreButton = Ui.secondaryButton(this, "Load more");
        loadMoreButton.setVisibility(View.GONE);
        body.addView(loadMoreButton, matchWrap());

        refreshButton.setOnClickListener(view -> loadShelf(true));
        syncButton.setOnClickListener(view -> startSync());
        searchButton.setOnClickListener(view -> loadShelf(true));
        queryInput.setOnEditorActionListener((view, actionId, event) -> {
            boolean submitted = actionId == EditorInfo.IME_ACTION_SEARCH
                    || (event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER);
            if (submitted) {
                loadShelf(true);
            }
            return submitted;
        });
        typeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                // Filters apply when Search is pressed, so typing does not cause surprise requests.
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        loadMoreButton.setOnClickListener(view -> loadShelf(false));

        setContentView(screen);
        loadShelf(true);
    }

    private void loadShelf(boolean reset) {
        if (api == null) {
            return;
        }
        if (reset) {
            activeQuery = queryInput.getText().toString().trim();
            activeType = FILTER_VALUES[typeSpinner.getSelectedItemPosition()];
            nextOffset = 0;
        }
        int requestedOffset = reset ? 0 : nextOffset;
        int generation = ++requestGeneration;
        setLoading(true, reset);

        executor.execute(() -> {
            try {
                JSONObject status = reset ? api.status() : null;
                Models.ItemPage page = api.items(
                        activeQuery,
                        activeType,
                        PAGE_SIZE,
                        requestedOffset
                );
                runOnUiThread(() -> {
                    if (generation != requestGeneration || isFinishing()) {
                        return;
                    }
                    if (status != null) {
                        renderStatus(status);
                    }
                    renderPage(page, reset);
                    setLoading(false, reset);
                });
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    if (generation != requestGeneration || isFinishing()) {
                        return;
                    }
                    setLoading(false, reset);
                    String error = ApiClient.friendlyError(exception);
                    if (reset && itemList.getChildCount() == 0) {
                        message.setText(error);
                        message.setTextColor(Ui.ERROR);
                        message.setVisibility(View.VISIBLE);
                    } else {
                        Toast.makeText(this, error, Toast.LENGTH_LONG).show();
                    }
                });
            }
        });
    }

    private void renderStatus(JSONObject status) {
        int count = status.optInt("item_count", 0);
        JSONObject sync = status.optJSONObject("sync");
        boolean running = sync != null && sync.optBoolean("running", false);
        boolean stopping = sync != null && sync.optBoolean("stopping", false);
        String state = stopping ? "stopping" : running ? "syncing" : "idle";
        String next = status.optString("next_scheduled_sync", "");
        String summary = String.format(Locale.getDefault(), "%d archived · %s", count, state);
        if (!next.isBlank() && !next.equals("null")) {
            summary += "\nNext scheduled sync: " + Ui.displayDate(next);
        }
        statusText.setText(summary);
        syncButton.setEnabled(!running);
        syncButton.setText(running ? "Syncing…" : "Sync now");
    }

    private void renderPage(Models.ItemPage page, boolean reset) {
        if (reset) {
            itemList.removeAllViews();
        }
        for (Models.ItemSummary item : page.items) {
            itemList.addView(itemCard(item));
        }
        nextOffset = page.offset + page.items.size();
        boolean hasMore = nextOffset < page.total;
        loadMoreButton.setVisibility(hasMore ? View.VISIBLE : View.GONE);

        if (itemList.getChildCount() == 0) {
            message.setText(activeQuery.isBlank() && activeType.isBlank()
                    ? "Your archive is empty. Start a sync from the web app or tap Sync now."
                    : "No archived posts match this search.");
            message.setTextColor(Ui.MUTED);
            message.setVisibility(View.VISIBLE);
        } else {
            message.setVisibility(View.GONE);
        }
    }

    private View itemCard(Models.ItemSummary item) {
        LinearLayout card = Ui.card(this);
        card.setClickable(true);
        card.setFocusable(true);
        card.setForeground(getDrawable(android.R.drawable.list_selector_background));

        FrameLayout mediaFrame = new FrameLayout(this);
        mediaFrame.setBackground(Ui.roundRect(Ui.SAND, 12, 0, Color.TRANSPARENT, this));
        card.addView(mediaFrame, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                Ui.dp(this, 220)
        ));

        if (item.coverUrl != null) {
            ImageView image = new ImageView(this);
            image.setScaleType(ImageView.ScaleType.CENTER_CROP);
            image.setContentDescription("Preview for post by " + item.author);
            mediaFrame.addView(image, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
            ));

            ProgressBar imageProgress = new ProgressBar(this);
            FrameLayout.LayoutParams imageProgressParams = new FrameLayout.LayoutParams(
                    Ui.dp(this, 38),
                    Ui.dp(this, 38),
                    Gravity.CENTER
            );
            mediaFrame.addView(imageProgress, imageProgressParams);
            ImageLoader.load(image, imageProgress, item.coverUrl, api);
        } else {
            TextView placeholder = Ui.text(this, "No preview", 14, Ui.MUTED);
            placeholder.setGravity(Gravity.CENTER);
            mediaFrame.addView(placeholder, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
            ));
        }

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams headerParams = matchWrap();
        headerParams.setMargins(0, Ui.dp(this, 14), 0, Ui.dp(this, 8));
        card.addView(header, headerParams);

        TextView author = Ui.heading(this, "@" + item.author, 17);
        author.setSingleLine(true);
        header.addView(author, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        String mediaLabel = item.mediaType;
        if (item.mediaCount > 1) {
            mediaLabel += " · " + item.mediaCount;
        }
        header.addView(Ui.badge(this, mediaLabel), wrapWrap());

        if (!item.caption.isBlank()) {
            TextView caption = Ui.text(this, item.caption, 15, Ui.INK);
            caption.setMaxLines(3);
            caption.setEllipsize(android.text.TextUtils.TruncateAt.END);
            card.addView(caption, matchWrap());
        }

        TextView date = Ui.text(
                this,
                "Saved " + Ui.displayDate(item.downloadedAt),
                12,
                Ui.MUTED
        );
        LinearLayout.LayoutParams dateParams = matchWrap();
        dateParams.setMargins(0, Ui.dp(this, 10), 0, 0);
        card.addView(date, dateParams);

        card.setOnClickListener(view -> {
            Intent intent = new Intent(this, DetailActivity.class);
            intent.putExtra(DetailActivity.EXTRA_ITEM_ID, item.id);
            startActivity(intent);
        });
        return card;
    }

    private void startSync() {
        if (api == null) {
            return;
        }
        syncButton.setEnabled(false);
        syncButton.setText(R.string.sync_starting);
        int generation = ++requestGeneration;
        executor.execute(() -> {
            try {
                JSONObject result = api.startSync();
                boolean started = result.optBoolean("started", false);
                runOnUiThread(() -> {
                    if (generation != requestGeneration || isFinishing()) {
                        return;
                    }
                    Toast.makeText(
                            this,
                            started ? "Synchronization started" : "A synchronization is already active",
                            Toast.LENGTH_SHORT
                    ).show();
                    loadShelf(true);
                });
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    if (generation != requestGeneration || isFinishing()) {
                        return;
                    }
                    syncButton.setEnabled(true);
                    syncButton.setText(R.string.sync_now);
                    Toast.makeText(
                            this,
                            ApiClient.friendlyError(exception),
                            Toast.LENGTH_LONG
                    ).show();
                });
            }
        });
    }

    private void setLoading(boolean loading, boolean reset) {
        progress.setVisibility(loading ? View.VISIBLE : View.GONE);
        refreshButton.setEnabled(!loading);
        searchButton.setEnabled(!loading);
        loadMoreButton.setEnabled(!loading);
        if (loading && reset) {
            message.setVisibility(View.GONE);
        }
    }

    private Button toolbarButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextColor(Ui.WHITE);
        button.setTextSize(13);
        button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Ui.GREEN_DARK));
        return button;
    }

    private void showInlineError(TextView view, String error) {
        view.setText(error == null ? "Connection failed" : error);
        view.setVisibility(View.VISIBLE);
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
