/*
 * Copyright 2026 DH FleetView contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package org.traccar.media;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.inject.Inject;
import jakarta.inject.Singleton;
import org.traccar.config.Config;
import org.traccar.config.Keys;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

@Singleton
public class Cmsv9Manager {

    private static final Logger LOG = LoggerFactory.getLogger(Cmsv9Manager.class);
    private static final Duration TIMEOUT = Duration.ofSeconds(30);
    private static final String WS_KEY = "J04Tb9pcLF7y6QrFmgTJLeVv33YbMhqW";

    private final Config config;
    private final ObjectMapper objectMapper;
    private final HttpClient client;
    private final Object wsOrderLock = new Object();
    private volatile String loginToken = "";

    @Inject
    public Cmsv9Manager(Config config, ObjectMapper objectMapper) {
        this.config = config;
        this.objectMapper = objectMapper;
        try {
            X509TrustManager trustAll = new X509TrustManager() {
                public X509Certificate[] getAcceptedIssuers() { return null; }
                public void checkClientTrusted(X509Certificate[] c, String a) {}
                public void checkServerTrusted(X509Certificate[] c, String a) {}
            };
            SSLContext sslContext = SSLContext.getInstance("TLS");
            sslContext.init(null, new TrustManager[]{trustAll}, new SecureRandom());
            client = HttpClient.newBuilder()
                    .connectTimeout(TIMEOUT)
                    .sslContext(sslContext)
                    .followRedirects(HttpClient.Redirect.NORMAL)
                    .build();
        } catch (Exception e) {
            throw new RuntimeException("Failed to create HTTP client", e);
        }
    }

    public boolean isConfigured() {
        return value(Keys.CMSV9_URL) != null
                && value(Keys.CMSV9_ACCOUNT) != null
                && value(Keys.CMSV9_PASSWORD) != null;
    }

    public int getMediaPort() {
        return config.getInteger(Keys.CMSV9_MEDIA_PORT);
    }

    public int getChannels() {
        return config.getInteger(Keys.CMSV9_CHANNELS);
    }

    public int getClientPort() {
        return config.getInteger(Keys.CMSV9_CLIENT_PORT);
    }

    public int getWsPort() {
        return config.getInteger(Keys.CMSV9_WS_PORT);
    }

    // --- FLV URL construction ---

    public String buildLiveFlvUrl(String terminal, int channel) {
        String host = apiUri("").getHost();
        int port = getMediaPort();
        return "https://" + host + ":" + port
                + "/live/0" + terminal + "_channel_" + channel + ".live.flv";
    }

    public String buildPlaybackFlvUrl(String terminal, int channel) {
        String host = apiUri("").getHost();
        int port = getMediaPort();
        return "https://" + host + ":" + port
                + "/live/0" + terminal + "_channel_" + channel + "_playback.live.flv";
    }

    public String rtmpToFlv(String rtmpUrl) {
        if (rtmpUrl == null || !rtmpUrl.startsWith("rtmp://")) {
            return rtmpUrl;
        }
        String withoutScheme = rtmpUrl.substring("rtmp://".length());
        int slashIdx = withoutScheme.indexOf('/');
        String host = withoutScheme.substring(0, slashIdx);
        String streamPath = withoutScheme.substring(slashIdx + 1);
        int clientPort = getClientPort();
        return "https://" + host + ":" + getMediaPort()
                + "/flv?port=" + clientPort + "&app=live&stream=" + streamPath;
    }

    // --- CNMS REST API ---

    public JsonNode login() throws Exception {
        String username = require(Keys.CMSV9_ACCOUNT);
        String passwordMd5 = md5(require(Keys.CMSV9_PASSWORD)).toLowerCase();
        String tradeno = String.valueOf(Instant.now().getEpochSecond());
        String sign = md5(username + passwordMd5 + tradeno).toUpperCase();

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("username", username);
        body.put("password", passwordMd5);
        body.put("tradeno", tradeno);
        body.put("sign", sign);

        LOG.info("CNMS login as {}", username);
        JsonNode response = post("/ajax/cmsapi/userLogin", body);
        int errCode = response.path("errCode").asInt(-1);
        if (errCode != 0) {
            String msg = response.path("resultMsg").asText("unknown error");
            LOG.error("CNMS login failed: errCode={}, msg={}", errCode, msg);
            throw new IOException("CNMS login failed: " + msg);
        }
        loginToken = response.path("token").asText("");
        LOG.info("CNMS login succeeded, token={}", loginToken);
        return response;
    }

    public JsonNode deptTree() throws Exception {
        return signedPost("/ajax/cmsapi/deptTree", new LinkedHashMap<>());
    }

    public int getDeviceChannels(String terminal) throws Exception {
        JsonNode response = deptTree();
        JsonNode list = response.path("resultData");
        if (list.isArray()) {
            for (JsonNode node : list) {
                if (node.path("nodetype").asInt(0) == 2
                        && terminal.equals(node.path("terminal").asText(""))) {
                    int channels = node.path("channeltotals").asInt(0);
                    if (channels > 0) {
                        return channels;
                    }
                }
            }
        }
        return -1;
    }

    public JsonNode playSend(String terminal, String channel, boolean start) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("type", start ? "1" : "0");
        body.put("terminal", terminal);
        body.put("id", String.valueOf(channel));
        body.put("protocol", "1");
        body.put("vedioType", "0");
        body.put("streamType", "1");

        JsonNode response = signedPost("/ajax/cmsapi/playSend", body);
        int errCode = response.path("errCode").asInt(-1);
        if (errCode != 0) {
            LOG.error("playSend failed: {}", response.path("resultMsg").asText());
        }
        return response;
    }

    public JsonNode playbackAppoint(
            String terminal, String channel, String startTime, String endTime) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("terminal", terminal);
        body.put("id", String.valueOf(channel));
        body.put("streamType", "0");
        body.put("vedioType", "0");
        body.put("memoryType", "1");
        body.put("startTime", startTime);
        body.put("endTime", endTime);

        JsonNode response = signedPost("/ajax/cmsapi/playbackAppoint", body);
        int errCode = response.path("errCode").asInt(-1);
        if (errCode != 0) {
            LOG.error("playbackAppoint failed: {}", response.path("resultMsg").asText());
        }
        return response;
    }

    public JsonNode queryTerminalFileList(
            String terminal, String channel, String startTime, String endTime) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("terminal", terminal);
        body.put("id", String.valueOf(channel));
        body.put("streamType", "0");
        body.put("vedioType", "0");
        body.put("memoryType", "1");
        body.put("startTime", startTime);
        body.put("endTime", endTime);

        return signedPost("/ajax/cmsapi/queryTerminalFileList", body);
    }

    public JsonNode getGpsStatus(String terminal) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("terminal", terminal);
        return signedPost("/ajax/cmsapi/getGpsStatus", body);
    }

    public JsonNode getDownVideosAndPictures(
            String terminal, String startTime, String endTime, String type) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("terminal", terminal);
        body.put("startTime", startTime);
        body.put("endTime", endTime);
        body.put("type", type);
        return signedPost("/ajax/Cmsapi/getDownVideos_and_pictures", body);
    }

    // --- WebSocket play/stop commands ---

    public boolean wsPlay(String terminal, int channel) {
        return wsSendOrderOnce(terminal, "9101",
                videoServerHost() + "," + videoServerPort() + ",0," + (channel) + ",0,1");
    }

    /**
     * Plays one live channel and waits until its stream is registered on the
     * local ZLMediaKit. The whole sequence is serialized so that concurrent
     * multiview requests start channels one at a time (the device drops
     * channels when commands arrive in quick succession).
     */
    public boolean playLiveAndWait(String terminal, int channel, long timeoutMillis) {
        synchronized (wsOrderLock) {
            if (!wsPlay(terminal, channel)) {
                return false;
            }
            return waitForStreamLive(liveStreamName(terminal, channel), timeoutMillis);
        }
    }

    public String liveStreamName(String terminal, int channel) {
        return "0" + terminal + "_channel_" + channel;
    }

    /**
     * Polls the local ZLMediaKit API until the named stream appears.
     * Avoids HTTP requests to the stream URL (which would trigger the
     * CNMS on-demand hooks and overload the video backend).
     */
    public boolean waitForStreamLive(String streamName, long timeoutMillis) {
        String secret = value(Keys.CMSV9_MEDIA_SECRET);
        if (secret == null) {
            LOG.warn("cmsv9.mediaSecret not configured, skipping stream wait");
            return true;
        }
        long deadline = System.currentTimeMillis() + timeoutMillis;
        while (System.currentTimeMillis() < deadline) {
            try {
                URI uri = URI.create("https://127.0.0.1:" + getMediaPort()
                        + "/index/api/getMediaList?secret=" + secret);
                HttpRequest request = HttpRequest.newBuilder(uri)
                        .timeout(Duration.ofSeconds(5))
                        .GET()
                        .build();
                HttpResponse<String> response = client.send(
                        request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() / 100 == 2) {
                    JsonNode root = objectMapper.readTree(response.body());
                    JsonNode data = root.path("data");
                    if (data.isArray()) {
                        for (JsonNode item : data) {
                            if (streamName.equals(item.path("stream").asText(""))) {
                                return true;
                            }
                        }
                    }
                }
            } catch (Exception e) {
                // keep polling
            }
            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return false;
            }
        }
        LOG.warn("Stream {} did not appear within {}s", streamName, timeoutMillis / 1000);
        return false;
    }

    public boolean wsStop(String terminal, int channel) {
        return wsSendOrderOnce(terminal, "9102", channel + ",0,0,0");
    }

    public boolean wsPlayback(String terminal, int channel, String startTime, String endTime) {
        return wsSendOrderOnce(terminal, "9201",
                videoServerHost() + "," + playbackPort() + ",0," + (channel) + ",0,1,1,0,0,"
                + startTime + "," + endTime);
    }

    public boolean wsStopPlayback(String terminal, int channel) {
        return wsSendOrderOnce(terminal, "9202", channel + ",0,0");
    }

    private boolean wsSendOrderOnce(String terminal, String order, String content) {
        synchronized (wsOrderLock) {
            for (int attempt = 0; attempt < 2; attempt++) {
                try {
                    if (loginToken.isEmpty()) {
                        login();
                    }
                    if (wsConnectLoginAndSend(terminal, order, content)) {
                        return true;
                    }
                    LOG.warn("WS order not acknowledged ({} {}), refreshing CNMS session...", order, terminal);
                    loginToken = "";
                } catch (Exception e) {
                    LOG.error("WS order failed: {} {} - {}", order, terminal, e.getMessage());
                    loginToken = "";
                }
            }
            return false;
        }
    }

    private boolean wsConnectLoginAndSend(String terminal, String order, String content)
            throws Exception {
        String host = apiUri("").getHost();
        int port = getWsPort();
        String url = "wss://" + host + ":" + port + "/Order";

        CountDownLatch doneLatch = new CountDownLatch(1);
        AtomicBoolean success = new AtomicBoolean(false);
        AtomicReference<String> orderId = new AtomicReference<>();
        AtomicReference<WebSocket> wsRef = new AtomicReference<>();

        SSLContext sslContext = SSLContext.getInstance("TLS");
        sslContext.init(null, new TrustManager[]{
            new X509TrustManager() {
                public X509Certificate[] getAcceptedIssuers() { return null; }
                public void checkClientTrusted(X509Certificate[] c, String a) {}
                public void checkServerTrusted(X509Certificate[] c, String a) {}
            }
        }, new SecureRandom());

        HttpClient wsClient = HttpClient.newBuilder()
                .sslContext(sslContext)
                .connectTimeout(TIMEOUT)
                .build();

        WebSocket.Listener listener = new WebSocket.Listener() {
            private final AtomicBoolean loggedIn = new AtomicBoolean(false);

            @Override
            public void onOpen(WebSocket webSocket) {
                wsRef.set(webSocket);
                WebSocket.Listener.super.onOpen(webSocket);
            }

            @Override
            public CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
                String msg = data.toString();
                LOG.info("WS recv: {}", msg);
                try {
                    JsonNode json = objectMapper.readTree(msg);
                    String type = json.path("type").asText("");
                    String id = json.path("id").asText("");
                    if (!id.isEmpty()) {
                        orderId.set(id);
                    }

                    if ("answer".equals(type)) {
                        int result = json.path("content").path("result").asInt(0);
                        if (result == 1 && !loggedIn.getAndSet(true)) {
                            LOG.info("WS login required, sending login...");
                            sendWsLoginMsg(webSocket, id);
                        } else if (result == 4) {
                            LOG.info("WS login acknowledged (result=4), sending order...");
                            sendWsOrderMsg(webSocket, id, terminal, order, content);
                            Thread.sleep(300);
                            sendWsOrderMsg(webSocket, id, terminal, order, content);
                            Thread.sleep(300);
                            sendWsOrderMsg(webSocket, id, terminal, order, content);
                            success.set(true);
                            LOG.info("WS order sent 3 times, waiting 1s for relay...");
                            Thread.sleep(1000);
                            doneLatch.countDown();
                        } else {
                            LOG.info("WS answer result={}, waiting...", result);
                        }
                    } else {
                        LOG.info("WS response type={}, done", type);
                    }
                } catch (Exception e) {
                    LOG.error("WS msg error: {}", e.getMessage());
                }
                return WebSocket.Listener.super.onText(webSocket, data, last);
            }

            @Override
            public CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
                LOG.info("WS closed: {} {}", statusCode, reason);
                doneLatch.countDown();
                return WebSocket.Listener.super.onClose(webSocket, statusCode, reason);
            }

            @Override
            public void onError(WebSocket webSocket, Throwable error) {
                LOG.error("WS error: {}", error.getMessage());
                doneLatch.countDown();
            }
        };

        wsClient.newWebSocketBuilder()
                .connectTimeout(TIMEOUT)
                .buildAsync(URI.create(url), listener)
                .get(10, TimeUnit.SECONDS);

        doneLatch.await(15, TimeUnit.SECONDS);
        WebSocket ws = wsRef.get();
        if (ws != null) {
            try { ws.sendClose(1000, "done"); } catch (Exception ignored) {}
        }
        return success.get();
    }

    private void sendWsLoginMsg(WebSocket webSocket, String orderId) {
        try {
            long time = Instant.now().getEpochSecond();
            String username = require(Keys.CMSV9_ACCOUNT);
            String signInput = "time=" + time
                    + "&username=" + username.toLowerCase()
                    + "&userpwd=" + require(Keys.CMSV9_PASSWORD).toLowerCase()
                    + "&key=" + WS_KEY.toLowerCase();
            String sign = md5(signInput).toUpperCase();

            ObjectNode msg = objectMapper.createObjectNode();
            msg.put("id", orderId);
            msg.put("type", "login");
            ObjectNode c = objectMapper.createObjectNode();
            c.put("username", "");
            c.put("password", "");
            c.put("session", loginToken);
            c.put("SubscribeType", 2);
            msg.set("content", c);
            msg.put("username", username);
            msg.put("time", time);
            msg.put("sign", sign);

            String json = objectMapper.writeValueAsString(msg);
            LOG.info("WS login: {}", json);
            webSocket.sendText(json, true);
        } catch (Exception e) {
            LOG.error("WS login failed: {}", e.getMessage());
        }
    }

    private void sendWsOrderMsg(WebSocket webSocket, String orderId,
            String terminal, String order, String content) {
        try {
            long time = Instant.now().getEpochSecond();
            String username = require(Keys.CMSV9_ACCOUNT);
            String signInput = "time=" + time
                    + "&username=" + username.toLowerCase()
                    + "&userpwd=" + require(Keys.CMSV9_PASSWORD).toLowerCase()
                    + "&key=" + WS_KEY.toLowerCase();
            String sign = md5(signInput).toUpperCase();

            ObjectNode msg = objectMapper.createObjectNode();
            msg.put("id", orderId);
            msg.put("type", "order");
            ObjectNode c = objectMapper.createObjectNode();
            c.put("deviceid", terminal);
            c.put("order", order);
            c.put("content", content);
            msg.set("content", c);
            msg.put("username", username);
            msg.put("time", time);
            msg.put("sign", sign);

            String json = objectMapper.writeValueAsString(msg);
            LOG.info("WS send order {} to {}: {}", order, terminal, content);
            webSocket.sendText(json, true);
        } catch (Exception e) {
            LOG.error("WS order send failed: {}", e.getMessage());
        }
    }

    // --- Helpers ---

    private String videoServerHost() {
        return apiUri("").getHost();
    }

    private int videoServerPort() {
        return 9500;
    }

    private int playbackPort() {
        return 9600;
    }

    private JsonNode signedPost(String path, Map<String, Object> extra) throws Exception {
        String username = require(Keys.CMSV9_ACCOUNT);
        String passwordMd5 = md5(require(Keys.CMSV9_PASSWORD)).toLowerCase();
        String tradeno = String.valueOf(Instant.now().getEpochSecond());
        String sign = md5(username + passwordMd5 + tradeno).toUpperCase();

        Map<String, Object> body = new LinkedHashMap<>(extra);
        body.put("username", username);
        body.put("tradeno", tradeno);
        body.put("sign", sign);

        return post(path, body);
    }

    private JsonNode post(String path, Map<String, Object> body) throws Exception {
        String json = objectMapper.writeValueAsString(body);
        HttpRequest request = HttpRequest.newBuilder(apiUri(path))
                .timeout(TIMEOUT)
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .header("Content-Type", "application/json")
                .build();
        HttpResponse<String> response = client.send(
                request, HttpResponse.BodyHandlers.ofString());
        String responseBody = stripBom(response.body());
        if (response.statusCode() / 100 != 2) {
            throw new IOException("CNMS HTTP " + response.statusCode() + ": " + responseBody);
        }
        LOG.debug("CNMS {} -> {}", path, responseBody);
        return objectMapper.readTree(responseBody);
    }

    private URI apiUri(String path) {
        String url = value(Keys.CMSV9_URL);
        URI uri = URI.create(url);
        return URI.create(uri.getScheme() + "://" + uri.getAuthority() + path);
    }

    private String value(org.traccar.config.ConfigKey<String> key) {
        String val = config.getString(key);
        return val != null && !val.isBlank() ? val : null;
    }

    private String require(org.traccar.config.ConfigKey<String> key) {
        String val = value(key);
        if (val == null) {
            throw new IllegalStateException("Config key " + key + " is not set");
        }
        return val;
    }

    private static String stripBom(String s) {
        if (s != null && !s.isEmpty() && s.charAt(0) == '\uFEFF') {
            return s.substring(1);
        }
        return s;
    }

    private static String md5(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException("MD5 failed", e);
        }
    }
}
