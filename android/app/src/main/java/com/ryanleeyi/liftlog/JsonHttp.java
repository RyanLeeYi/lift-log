package com.ryanleeyi.liftlog;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** 兩個 sync HTTP call 共用的窄邊界；限制 redirect 與 response 大小，避免洩漏 token/吃滿記憶體。 */
final class JsonHttp {
    private static final int MAX_RESPONSE_BYTES = 8 * 1024 * 1024;

    private JsonHttp() {}

    static final class Response {
        final int status;
        final JSONObject body;

        Response(int status, JSONObject body) {
            this.status = status;
            this.body = body;
        }
    }

    static Response request(
        String baseUrl, String path, String method, JSONObject body, String bearerToken
    ) throws IOException, JSONException {
        URL url = safeUrl(baseUrl, path);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(15_000);
            connection.setRequestMethod(method);
            connection.setRequestProperty("Accept", "application/json");
            if (bearerToken != null && !bearerToken.isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + bearerToken);
            }
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(bytes.length);
                connection.setRequestProperty("Content-Type", "application/json");
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(bytes);
                }
            }
            int status = connection.getResponseCode();
            InputStream stream = status >= 400
                ? connection.getErrorStream() : connection.getInputStream();
            JSONObject response = new JSONObject();
            if (stream != null) {
                byte[] bytes = readLimited(stream);
                if (bytes.length > 0) {
                    response = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
                }
            }
            return new Response(status, response);
        } finally {
            connection.disconnect();
        }
    }

    static URL safeUrl(String baseUrl, String path) throws IOException {
        if (baseUrl == null || path == null || !path.startsWith("/")) {
            throw new IOException("sync base URL 未設定");
        }
        URL base = new URL(baseUrl);
        String scheme = base.getProtocol();
        String host = base.getHost();
        boolean localHttp = scheme.equals("http") && (
            host.equals("localhost") || host.equals("127.0.0.1") || host.equals("10.0.2.2")
        );
        if ((!scheme.equals("https") && !localHttp) || base.getUserInfo() != null
            || !base.getPath().matches("/?") || base.getQuery() != null || base.getRef() != null) {
            throw new IOException("sync base URL 不安全");
        }
        String normalized = baseUrl.endsWith("/")
            ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        return new URL(normalized + path);
    }

    private static byte[] readLimited(InputStream stream) throws IOException {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int total = 0;
            int read;
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > MAX_RESPONSE_BYTES) throw new IOException("sync response 過大");
                output.write(buffer, 0, read);
            }
            return output.toByteArray();
        }
    }
}
