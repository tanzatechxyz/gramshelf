package xyz.tanzatech.gramshelf;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.LruCache;
import android.view.View;
import android.widget.ImageView;
import android.widget.ProgressBar;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class ImageLoader {
    private static final ExecutorService EXECUTOR = Executors.newFixedThreadPool(3);
    private static final int CACHE_KIB = (int) (Runtime.getRuntime().maxMemory() / 1024L / 12L);
    private static final LruCache<String, Bitmap> CACHE = new LruCache<>(CACHE_KIB) {
        @Override
        protected int sizeOf(String key, Bitmap bitmap) {
            return bitmap.getByteCount() / 1024;
        }
    };

    private ImageLoader() {
    }

    static void load(ImageView view, ProgressBar progress, String url, ApiClient client) {
        view.setTag(url);
        Bitmap cached = CACHE.get(url);
        if (cached != null) {
            progress.setVisibility(View.GONE);
            view.setImageBitmap(cached);
            return;
        }

        progress.setVisibility(View.VISIBLE);
        EXECUTOR.execute(() -> {
            Bitmap bitmap = null;
            try {
                byte[] bytes = client.image(url);
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);

                BitmapFactory.Options options = new BitmapFactory.Options();
                options.inSampleSize = sampleSize(bounds.outWidth, bounds.outHeight, 1400);
                options.inPreferredConfig = Bitmap.Config.RGB_565;
                bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options);
                if (bitmap != null) {
                    CACHE.put(url, bitmap);
                }
            } catch (RuntimeException | java.io.IOException ignored) {
                // A neutral placeholder remains visible when a single media request fails.
            }

            Bitmap result = bitmap;
            view.post(() -> {
                if (!url.equals(view.getTag())) {
                    return;
                }
                progress.setVisibility(View.GONE);
                if (result != null) {
                    view.setImageBitmap(result);
                }
            });
        });
    }

    private static int sampleSize(int width, int height, int maxDimension) {
        int sample = 1;
        while (width / sample > maxDimension * 2 || height / sample > maxDimension * 2) {
            sample *= 2;
        }
        return sample;
    }
}
