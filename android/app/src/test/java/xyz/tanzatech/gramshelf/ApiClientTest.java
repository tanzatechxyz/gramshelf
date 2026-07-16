package xyz.tanzatech.gramshelf;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

public final class ApiClientTest {
    @Test
    public void normalizesTrailingSlashes() {
        assertEquals(
                "http://192.168.1.20:8080",
                ApiClient.normalizeBaseUrl("  http://192.168.1.20:8080///  ")
        );
    }

    @Test
    public void preservesReverseProxyPath() {
        assertEquals(
                "https://home.example/gramshelf",
                ApiClient.normalizeBaseUrl("https://home.example/gramshelf/")
        );
    }

    @Test
    public void rejectsNonHttpSchemes() {
        assertThrows(
                IllegalArgumentException.class,
                () -> ApiClient.normalizeBaseUrl("file:///tmp/gramshelf")
        );
    }

    @Test
    public void rejectsCredentialsAndQuery() {
        assertThrows(
                IllegalArgumentException.class,
                () -> ApiClient.normalizeBaseUrl("https://user@example.com/?token=nope")
        );
    }
}
