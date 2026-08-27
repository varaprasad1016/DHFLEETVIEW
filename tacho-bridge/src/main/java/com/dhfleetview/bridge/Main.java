package com.dhfleetview.bridge;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Tacho Bridge main application for Windows (Linux support can be added later).
 *
 * <p>Responsibilities:
 * <ul>
 *   <li>Detect PC/SC readers and company cards via {@link SmartCardReader}.
 *   <li>Register with the FastHosts server using a one-time pairing code.
 *   <li>Send periodic heartbeats with reader/card status.
 *   <li>Handle server-initiated authentication operations (mock for MVP).
 * </ul>
 *
 * <p>Configuration: {@code bridge.properties} next to the JAR or at
 * {@code C:\DHFleetView\tacho-bridge\bridge.properties}.
 * Required keys: {@code serverUrl}, {@code bridgeId} (generated on first run if absent).
 */
public class Main {

    private static final Logger LOGGER = LoggerFactory.getLogger(Main.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final BridgeConfig config;
    private final SmartCardReader reader;
    private final HttpClient httpClient;
    private String bridgeToken;

    public Main(BridgeConfig config, SmartCardReader reader) {
        this.config = config;
        this.reader = reader;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    public static void main(String[] args) throws Exception {
        BridgeConfig config = BridgeConfig.load();
        SmartCardReader reader;
        if ("mock".equalsIgnoreCase(System.getProperty("tacho.reader", "pcsc"))) {
            reader = new MockSmartCardReader();
        } else {
            reader = new PcscSmartCardReader();
        }
        try {
            reader.connect();
        } catch (Exception e) {
            LOGGER.warn("No PC/SC reader available, using mock", e);
            reader = new MockSmartCardReader();
        }

        Main app = new Main(config, reader);

        if (args.length > 0 && "pair".equalsIgnoreCase(args[0]) && args.length > 1) {
            app.pair(args[1]);
            return;
        }

        if (config.getBridgeId() == null) {
            System.out.println("Bridge not registered. Run: java -jar tacho-bridge.jar pair <PAIRING_CODE>");
            System.out.println("Generate a pairing code in the web app: Tachograph > Bridges > Generate Pairing Code");
            return;
        }

        app.startHeartbeatLoop();
        app.startLocalStatusServer();

        // Keep the main thread alive
        Thread.currentThread().join();
    }

    private void pair(String pairingCode) throws Exception {
        String bridgeId = config.getBridgeId();
        if (bridgeId == null) {
            bridgeId = UUID.randomUUID().toString();
            config.setBridgeId(bridgeId);
            config.save();
        }

        Map<String, Object> body = new HashMap<>();
        body.put("pairingCode", pairingCode);
        body.put("bridgeId", bridgeId);
        body.put("name", config.getBridgeName() != null ? config.getBridgeName() : "Tacho Bridge");
        body.put("softwareVersion", "1.0.0");

        HttpRequest request = HttpRequest.newBuilder(
                        URI.create(config.getServerUrl() + "/api/tachograph/bridges/register"))
                .timeout(Duration.ofSeconds(15))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(body), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() / 100 != 2) {
            System.err.println("Pairing failed: HTTP " + response.statusCode() + " " + response.body());
            System.exit(1);
        }

        // Server returns bridge with token in tokenHash field for MVP
        Map<?, ?> result = MAPPER.readValue(response.body(), Map.class);
        String token = null;
        if (result.containsKey("tokenHash")) {
            token = (String) result.get("tokenHash");
        } else if (result.containsKey("token")) {
            token = (String) result.get("token");
        }
        if (token != null) {
            config.setBridgeToken(token);
            config.save();
            System.out.println("Bridge registered. Token saved.");
        } else {
            System.out.println("Bridge registered. Response: " + response.body());
        }
    }

    private void startHeartbeatLoop() {
        ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "tacho-heartbeat");
            t.setDaemon(true);
            return t;
        });
        scheduler.scheduleAtFixedRate(() -> {
            try {
                sendHeartbeat();
            } catch (Exception e) {
                LOGGER.warn("Heartbeat failed", e);
            }
        }, 0, 30, TimeUnit.SECONDS);
    }

    private void sendHeartbeat() throws Exception {
        if (config.getBridgeId() == null || config.getBridgeToken() == null) {
            return;
        }

        Long bridgeNumericId = config.getBridgeNumericId();
        if (bridgeNumericId == null) {
            // Resolve numeric id from bridgeId string via listBridges
            return;
        }

        Map<String, Object> body = new HashMap<>();
        body.put("readerStatus", reader.getReaderStatus().name());
        body.put("cardStatus", reader.getCardStatus().name());
        body.put("softwareVersion", "1.0.0");

        HttpRequest request = HttpRequest.newBuilder(
                        URI.create(config.getServerUrl()
                                + "/api/tachograph/bridges/" + bridgeNumericId + "/heartbeat"))
                .timeout(Duration.ofSeconds(10))
                .header("Content-Type", "application/json")
                .header("X-Bridge-Token", config.getBridgeToken())
                .POST(HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(body), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() / 100 == 2) {
            LOGGER.info("Heartbeat OK");
        } else {
            LOGGER.warn("Heartbeat failed: HTTP {} {}", response.statusCode(), response.body());
        }
    }

    private void startLocalStatusServer() {
        // Minimal localhost status server on 127.0.0.1 for diagnostics.
        // Binds only to loopback, never 0.0.0.0.
        try {
            com.sun.net.httpserver.HttpServer server =
                    com.sun.net.httpserver.HttpServer.create(
                            new java.net.InetSocketAddress("127.0.0.1", 8765), 0);
            server.createContext("/status", exchange -> {
                String json = String.format(
                        "{\"bridgeId\":\"%s\",\"server\":\"%s\",\"reader\":\"%s\",\"card\":\"%s\"}",
                        config.getBridgeId(), config.getServerUrl(),
                        reader.getReaderStatus(), reader.getCardStatus());
                byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, bytes.length);
                try (var os = exchange.getResponseBody()) {
                    os.write(bytes);
                }
            });
            server.setExecutor(Executors.newSingleThreadExecutor());
            server.start();
            LOGGER.info("Local status server on http://127.0.0.1:8765/status");
        } catch (IOException e) {
            LOGGER.warn("Failed to start local status server", e);
        }
    }
}
