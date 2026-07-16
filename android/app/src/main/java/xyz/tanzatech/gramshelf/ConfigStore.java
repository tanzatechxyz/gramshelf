package xyz.tanzatech.gramshelf;

import android.content.Context;
import android.content.SharedPreferences;

final class ConfigStore {
    private static final String PREFERENCES = "gramshelf_connection";
    private static final String KEY_SERVER = "server";
    private static final String KEY_TOKEN = "token";

    private final SharedPreferences preferences;

    ConfigStore(Context context) {
        preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    boolean isConfigured() {
        return !server().isBlank() && !token().isBlank();
    }

    String server() {
        return preferences.getString(KEY_SERVER, "");
    }

    String token() {
        return preferences.getString(KEY_TOKEN, "");
    }

    void save(String server, String token) {
        preferences.edit()
                .putString(KEY_SERVER, server)
                .putString(KEY_TOKEN, token)
                .apply();
    }

    void clear() {
        preferences.edit().clear().apply();
    }
}
