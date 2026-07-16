package xyz.tanzatech.gramshelf;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

final class Models {
    private Models() {
    }

    static final class ItemPage {
        final List<ItemSummary> items;
        final int total;
        final int limit;
        final int offset;

        ItemPage(List<ItemSummary> items, int total, int limit, int offset) {
            this.items = items;
            this.total = total;
            this.limit = limit;
            this.offset = offset;
        }

        static ItemPage fromJson(JSONObject json) throws JSONException {
            JSONArray source = json.getJSONArray("items");
            List<ItemSummary> items = new ArrayList<>(source.length());
            for (int index = 0; index < source.length(); index++) {
                items.add(ItemSummary.fromJson(source.getJSONObject(index)));
            }
            return new ItemPage(
                    items,
                    json.getInt("total"),
                    json.getInt("limit"),
                    json.getInt("offset")
            );
        }
    }

    static final class ItemSummary {
        final int id;
        final String shortcode;
        final String instagramUrl;
        final String author;
        final String caption;
        final String publishedAt;
        final String downloadedAt;
        final String mediaType;
        final String coverUrl;
        final int mediaCount;

        ItemSummary(
                int id,
                String shortcode,
                String instagramUrl,
                String author,
                String caption,
                String publishedAt,
                String downloadedAt,
                String mediaType,
                String coverUrl,
                int mediaCount
        ) {
            this.id = id;
            this.shortcode = shortcode;
            this.instagramUrl = instagramUrl;
            this.author = author;
            this.caption = caption;
            this.publishedAt = publishedAt;
            this.downloadedAt = downloadedAt;
            this.mediaType = mediaType;
            this.coverUrl = coverUrl;
            this.mediaCount = mediaCount;
        }

        static ItemSummary fromJson(JSONObject json) throws JSONException {
            return new ItemSummary(
                    json.getInt("id"),
                    json.getString("shortcode"),
                    json.getString("instagram_url"),
                    json.getString("author"),
                    json.optString("caption", ""),
                    json.getString("published_at"),
                    json.getString("downloaded_at"),
                    json.getString("media_type"),
                    nullableString(json, "cover_url"),
                    json.optInt("media_count", 0)
            );
        }
    }

    static final class ItemDetail {
        final int id;
        final String shortcode;
        final String instagramUrl;
        final String author;
        final String caption;
        final String publishedAt;
        final String downloadedAt;
        final String mediaType;
        final List<Media> media;

        ItemDetail(
                int id,
                String shortcode,
                String instagramUrl,
                String author,
                String caption,
                String publishedAt,
                String downloadedAt,
                String mediaType,
                List<Media> media
        ) {
            this.id = id;
            this.shortcode = shortcode;
            this.instagramUrl = instagramUrl;
            this.author = author;
            this.caption = caption;
            this.publishedAt = publishedAt;
            this.downloadedAt = downloadedAt;
            this.mediaType = mediaType;
            this.media = media;
        }

        static ItemDetail fromJson(JSONObject json) throws JSONException {
            JSONArray source = json.getJSONArray("media");
            List<Media> media = new ArrayList<>(source.length());
            for (int index = 0; index < source.length(); index++) {
                media.add(Media.fromJson(source.getJSONObject(index)));
            }
            return new ItemDetail(
                    json.getInt("id"),
                    json.getString("shortcode"),
                    json.getString("instagram_url"),
                    json.getString("author"),
                    json.optString("caption", ""),
                    json.getString("published_at"),
                    json.getString("downloaded_at"),
                    json.getString("media_type"),
                    media
            );
        }
    }

    static final class Media {
        final int position;
        final String kind;
        final String url;

        Media(int position, String kind, String url) {
            this.position = position;
            this.kind = kind;
            this.url = url;
        }

        static Media fromJson(JSONObject json) throws JSONException {
            return new Media(
                    json.getInt("position"),
                    json.getString("kind"),
                    json.getString("url")
            );
        }
    }

    private static String nullableString(JSONObject json, String key) {
        if (json.isNull(key)) {
            return null;
        }
        String value = json.optString(key, "");
        return value.isBlank() ? null : value;
    }
}
