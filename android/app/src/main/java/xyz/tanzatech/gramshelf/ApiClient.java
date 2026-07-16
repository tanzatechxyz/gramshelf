package xyz.tanzatech.gramshelf;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.UnsupportedEncodingException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

final class ApiClient {
    private static final int JSON_LIMIT_BYTES = 4 * 1024 * 1024;
    private static final int IMAGE_LIMIT_BYTES = 30 * 1024 * 1024;
    private static final String USER_AGENT = "GramShelf-Android/0.2.0";

    private final String baseUrl;
    private final String token;
    private final URI baseUri;

    ApiClient(String baseUrl, String token) {
        this.baseUrl = normalizeBaseUrl(baseUrl);
        this.token = token.trim();
        if (this.token.isBlank()) {
            throw new IllegalArgumentException("API token is required");
        }
        this.baseUri = URI.create(this.baseUrl);
    }

    static String normalizeBaseUrl(String input) {
        String value = input == null ? "" : input.trim();
        if (value.isBlank()) {
            throw new IllegalArgumentException("Server URL is required");
        }
        try {
            URI uri = new URI(value);
            String scheme = uri.getScheme();
            if (scheme == null
                    || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
                throw new IllegalArgumentException("Server URL must start with http:// or https://");
            }
            if (uri.getHost() == null || uri.getHost().isBlank()) {
                throw new IllegalArgumentException("Server URL needs a valid host name or IP address");
            }
            if (uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
                throw new IllegalArgumentException("Server URL cannot contain credentials, a query, or a fragment");
            }
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("Server URL is not valid", exception);
        }
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    JSONObject status() throws IOException, JSONException {
        return requestJson("GET", "/api/v1/status");
    }

    Models.ItemPage items(String query, String mediaType, int limit, int offset)
            throws IOException, JSONException {
        String path = "/api/v1/items?q=" + encode(query)
                + "&media_type=" + encode(mediaType)
                + "&limit=" + limit
                + "&offset=" + offset;
        return Models.ItemPage.fromJson(requestJson("GET", path));
    }

    Models.ItemDetail item(int itemId) throws IOException, JSONException {
        return Models.ItemDetail.fromJson(requestJson("GET", "/api/v1/items/" + itemId));
    }

    JSONObject startSync() throws IOException, JSONException {
        return requestJson("POST", "/api/v1/sync");
    }

    byte[] image(String url) throws IOException {
        URL verified = verifiedMediaUrl(url);
        HttpURLConnection connection = open(verified, "GET");
        try {
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) {
                throw apiError(connection, status);
            }
            return readLimited(connection.getInputStream(), IMAGE_LIMIT_BYTES);
        } finally {
            connection.disconnect();
        }
    }

    Map<String, String> mediaHeaders(String url) {
        verifiedMediaUrl(url);
        Map<String, String> headers = new HashMap<>();
        headers.put("Authorization", "Bearer " + token);
        headers.put("User-Agent", USER_AGENT);
        return headers;
    }

    private JSONObject requestJson(String method, String path) throws IOException, JSONException {
        URL url = URI.create(baseUrl + path).toURL();
        HttpURLConnection connection = open(url, method);
        if (method.equals("POST")) {
            connection.setDoOutput(true);
            connection.setFixedLengthStreamingMode(0);
        }
        try {
            if (method.equals("POST")) {
                connection.getOutputStream().close();
            }
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) {
                throw apiError(connection, status);
            }
            String response = new String(
                    readLimited(connection.getInputStream(), JSON_LIMIT_BYTES),
                    StandardCharsets.UTF_8
            );
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    private HttpURLConnection open(URL url, String method) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(10_000);
        connection.setReadTimeout(45_000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("User-Agent", USER_AGENT);
        return connection;
    }

    private URL verifiedMediaUrl(String value) {
        try {
            URI candidate = baseUri.resolve(value);
            if (!sameOrigin(baseUri, candidate)) {
                throw new IllegalArgumentException("GramShelf returned a media URL on another server");
            }
            return candidate.toURL();
        } catch (IllegalArgumentException | IOException exception) {
            throw new IllegalArgumentException("Invalid media URL", exception);
        }
    }

    private static boolean sameOrigin(URI first, URI second) {
        return first.getScheme().equalsIgnoreCase(second.getScheme())
                && first.getHost().equalsIgnoreCase(second.getHost())
                && effectivePort(first) == effectivePort(second);
    }

    private static int effectivePort(URI uri) {
        if (uri.getPort() >= 0) {
            return uri.getPort();
        }
        return uri.getScheme().equalsIgnoreCase("https") ? 443 : 80;
    }

    private static ApiException apiError(HttpURLConnection connection, int status) {
        String detail = "Request failed with HTTP " + status;
        InputStream stream = connection.getErrorStream();
        if (stream != null) {
            try {
                String body = new String(readLimited(stream, JSON_LIMIT_BYTES), StandardCharsets.UTF_8);
                JSONObject json = new JSONObject(body);
                detail = json.optString("detail", detail);
            } catch (IOException | JSONException ignored) {
                // The HTTP status remains useful when the server did not return a GramShelf error.
            }
        }
        if (status == HttpURLConnection.HTTP_UNAUTHORIZED) {
            detail = "The API token was rejected. Copy the current token from GramShelf Settings.";
        }
        return new ApiException(status, detail);
    }

    private static byte[] readLimited(InputStream input, int maxBytes) throws IOException {
        try (InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16 * 1024];
            int total = 0;
            int read;
            while ((read = source.read(buffer)) != -1) {
                total += read;
                if (total > maxBytes) {
                    throw new IOException("Server response is larger than the app limit");
                }
                output.write(buffer, 0, read);
            }
            return output.toByteArray();
        }
    }

    private static String encode(String value) {
        try {
            return URLEncoder.encode(
                    value == null ? "" : value,
                    StandardCharsets.UTF_8.name()
            );
        } catch (UnsupportedEncodingException impossible) {
            throw new IllegalStateException("UTF-8 is unavailable", impossible);
        }
    }

    static String friendlyError(Throwable throwable) {
        Throwable cause = throwable;
        while (cause.getCause() != null) {
            cause = cause.getCause();
        }
        String message = cause.getMessage();
        if (message == null || message.isBlank()) {
            return "Could not reach GramShelf. Check the server address and your network.";
        }
        String lower = message.toLowerCase(Locale.ROOT);
        if (lower.contains("cleartext") || lower.contains("failed to connect")
                || lower.contains("unable to resolve host") || lower.contains("timed out")) {
            return "Could not reach GramShelf. Check the server address and your network.";
        }
        return message;
    }

    static final class ApiException extends IOException {
        final int status;

        ApiException(int status, String message) {
            super(message);
            this.status = status;
        }
    }
}
