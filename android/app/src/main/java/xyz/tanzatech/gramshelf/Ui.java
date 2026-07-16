package xyz.tanzatech.gramshelf;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Locale;

final class Ui {
    static final int INK = Color.rgb(24, 33, 27);
    static final int MUTED = Color.rgb(91, 99, 93);
    static final int PAPER = Color.rgb(247, 244, 237);
    static final int GREEN = Color.rgb(23, 107, 74);
    static final int GREEN_DARK = Color.rgb(14, 78, 54);
    static final int SAND = Color.rgb(232, 224, 210);
    static final int WHITE = Color.WHITE;
    static final int ERROR = Color.rgb(154, 45, 36);

    private Ui() {
    }

    static int dp(Context context, int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    static TextView text(Context context, String value, float sizeSp, int color) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextSize(sizeSp);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.08f);
        return view;
    }

    static TextView heading(Context context, String value, float sizeSp) {
        TextView view = text(context, value, sizeSp, INK);
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    static TextView badge(Context context, String value) {
        TextView view = text(context, value.toUpperCase(Locale.ROOT), 11, GREEN_DARK);
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(context, 10), dp(context, 5), dp(context, 10), dp(context, 5));
        view.setBackground(roundRect(SAND, 999, 0, Color.TRANSPARENT, context));
        view.setSingleLine(true);
        view.setEllipsize(TextUtils.TruncateAt.END);
        return view;
    }

    static LinearLayout card(Context context) {
        LinearLayout card = new LinearLayout(context);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(context, 16), dp(context, 16), dp(context, 16), dp(context, 16));
        card.setBackground(roundRect(WHITE, 18, 1, Color.rgb(225, 220, 210), context));
        card.setElevation(dp(context, 2));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(0, 0, 0, dp(context, 14));
        card.setLayoutParams(params);
        return card;
    }

    static Button primaryButton(Context context, String label) {
        Button button = new Button(context);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextColor(WHITE);
        button.setTextSize(15);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setBackgroundTintList(ColorStateList.valueOf(GREEN));
        button.setMinHeight(dp(context, 48));
        return button;
    }

    static Button secondaryButton(Context context, String label) {
        Button button = new Button(context);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextColor(GREEN_DARK);
        button.setTextSize(14);
        button.setBackgroundTintList(ColorStateList.valueOf(SAND));
        button.setMinHeight(dp(context, 44));
        return button;
    }

    static GradientDrawable roundRect(
            int color,
            int radiusDp,
            int strokeDp,
            int strokeColor,
            Context context
    ) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(context, radiusDp));
        if (strokeDp > 0) {
            drawable.setStroke(dp(context, strokeDp), strokeColor);
        }
        return drawable;
    }

    static String displayDate(String value) {
        if (value == null || value.isBlank()) {
            return "Unknown date";
        }
        try {
            OffsetDateTime parsed = OffsetDateTime.parse(value.replace("Z", "+00:00"));
            return parsed.format(DateTimeFormatter.ofPattern("d MMM yyyy"));
        } catch (DateTimeParseException ignored) {
            return value;
        }
    }
}
