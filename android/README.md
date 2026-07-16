# GramShelf for Android

This directory contains a deliberately small native Android client for the existing GramShelf HTTP API.

## First release scope

- Connect to one self-hosted GramShelf server with its API token.
- View server and synchronization status.
- Browse the newest archived posts with authenticated cover images.
- Search captions, authors, and shortcodes and filter by media type.
- Open item details, image carousels, and authenticated videos.
- Start an on-demand synchronization.

Instagram login/session management, scheduler settings, diagnostics, legacy import, and author repair remain in the web UI. Keeping administrator-only maintenance in one place avoids duplicating fragile workflows in the first Android release.

The client uses Android framework APIs only. It has no UI, networking, image-loading, persistence, analytics, or DI libraries.

## Install

Download `dist/gramshelf-android-v0.1.0.apk` from the repository, allow installation from your browser or file manager when Android asks, then install it. This preview APK is debug-signed for direct sideloading.

In GramShelf's web UI, open **Settings**, copy the API token, and enter:

1. The full server address, including `http://` or `https://`, port, and optional reverse-proxy path.
2. The API token beginning with `gs_`.

The server must be reachable from the Android device. Android emulators use `10.0.2.2` to reach the development computer's localhost.

## Security

The API token is stored in this app's private preferences and excluded from Android backup. Media requests are restricted to the configured server origin so the token is not forwarded to a different host. Redirects are not followed for the same reason.

Cleartext HTTP is supported because GramShelf is commonly hosted on a trusted home LAN. Use HTTPS before connecting across the public internet. The app does not bypass invalid or self-signed TLS certificates.

## Build

Install JDK 17 and Android SDK Platform 35, then run:

```bash
cd android
./gradlew testDebugUnitTest lintDebug assembleDebug
```

The installable APK will be at `app/build/outputs/apk/debug/app-debug.apk`. Production distribution should use a private release signing key; no signing secret belongs in this repository.
