package com.dhfleetview.bridge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/**
 * Everything this bridge says to the DH FleetView server.
 *
 * <p>All traffic is outbound HTTPS. The bridge never listens for inbound connections, so it needs
 * no firewall change and no port forward on the customer's office network — which is what makes
 * it deployable on a machine an IT department will not otherwise touch.
 */
public class ServerClient {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Long-poll requests must outlive the server's own poll window. */
    private static final Duration POLL_TIMEOUT = Duration.ofSeconds(60);
    private static final Duration NORMAL_TIMEOUT = Duration.ofSeconds(20);

    /** What the server returns when a pairing code is exchanged for a token. */
    public static class Registration {
        private final long numericId;
        private final String token;
        private final String name;

        Registration(long numericId, String token, String name) {
            this.numericId = numericId;
            this.token = token;
            this.name = name;
        }

        public long getNumericId() {
            return numericId;
        }

        public String getToken() {
            return token;
        }

        public String getName() {
            return name;
        }
    }

    /** One piece of work the server wants performed against the card. */
    public static class CardTask {
        private final String type;
        private final String commandId;
        private final byte[] data;

        CardTask(String type, String commandId, byte[] data) {
            this.type = type;
            this.commandId = commandId;
            this.data = data;
        }

        public String getType() {
            return type;
        }

        public String getCommandId() {
            return commandId;
        }

        public byte[] getData() {
            return data;
        }
    }

    private final String serverUrl;
    private final HttpClient httpClient;

    public ServerClient(String serverUrl) {
        this.serverUrl = serverUrl.endsWith("/")
                ? serverUrl.substring(0, serverUrl.length() - 1) : serverUrl;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(15))
                .followRedirects(HttpClient.Redirect.NORMAL)
                .build();
    }

    /** Exchanges a one-time pairing code for a long-lived bridge token. */
    public Registration register(
            String pairingCode, String bridgeId, String name, String softwareVersion, String hostname)
            throws IOException, InterruptedException {

        Map<String, Object> body = new HashMap<>();
        body.put("pairingCode", pairingCode);
        body.put("bridgeId", bridgeId);
        body.put("name", name);
        body.put("softwareVersion", softwareVersion);
        body.put("hostname", hostname);

        HttpResponse<String> response = post("/api/tachograph/bridges/register", null, body, NORMAL_TIMEOUT);
        if (response.statusCode() / 100 != 2) {
            throw new IOException("Pairing failed: HTTP " + response.statusCode() + " " + response.body());
        }

        JsonNode node = MAPPER.readTree(response.body());
        String token = node.path("bridgeToken").asText(null);
        if (token == null || token.isEmpty()) {
            throw new IOException("The server did not return a bridge token");
        }
        return new Registration(node.path("id").asLong(), token, node.path("name").asText(name));
    }

    /** Reports reader and card state, and keeps the bridge marked online. */
    public void heartbeat(
            long numericId, String token, String readerStatus, String cardStatus,
            String softwareVersion, String hostname) throws IOException, InterruptedException {

        Map<String, Object> body = new HashMap<>();
        body.put("readerStatus", readerStatus);
        body.put("cardStatus", cardStatus);
        body.put("softwareVersion", softwareVersion);
        body.put("hostname", hostname);

        HttpResponse<String> response = post(
                "/api/tachograph/bridges/" + numericId + "/heartbeat", token, body, NORMAL_TIMEOUT);
        if (response.statusCode() / 100 != 2) {
            throw new IOException("Heartbeat failed: HTTP " + response.statusCode() + " " + response.body());
        }
    }

    /**
     * Waits for the next card command. The server holds the request open until it has work or its
     * poll window expires, so an idle bridge costs one request every half minute rather than a
     * steady stream of empty ones.
     *
     * @return the command, or null when the poll returned empty
     */
    public CardTask pollCard(long numericId, String token) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(
                        URI.create(serverUrl + "/api/tachograph/bridges/" + numericId + "/card/poll"))
                .timeout(POLL_TIMEOUT)
                .header("X-Bridge-Token", token)
                .GET()
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() / 100 != 2) {
            throw new IOException("Card poll failed: HTTP " + response.statusCode() + " " + response.body());
        }

        JsonNode node = MAPPER.readTree(response.body());
        String type = node.path("command").asText("NONE");
        if ("NONE".equals(type)) {
            return null;
        }
        String data = node.path("data").asText("");
        return new CardTask(
                type,
                node.path("commandId").asText(),
                data.isEmpty() ? new byte[0] : java.util.Base64.getDecoder().decode(data));
    }

    /** Returns the card's answer, or the reason there was not one. */
    public void respondCard(
            long numericId, String token, String commandId,
            byte[] data, String errorCode, String errorMessage)
            throws IOException, InterruptedException {

        Map<String, Object> body = new HashMap<>();
        body.put("commandId", commandId);
        if (errorCode != null) {
            body.put("errorCode", errorCode);
            body.put("errorMessage", errorMessage);
        } else {
            body.put("data", java.util.Base64.getEncoder().encodeToString(data));
        }

        HttpResponse<String> response = post(
                "/api/tachograph/bridges/" + numericId + "/card/respond", token, body, NORMAL_TIMEOUT);
        if (response.statusCode() / 100 != 2) {
            throw new IOException(
                    "Card response rejected: HTTP " + response.statusCode() + " " + response.body());
        }
    }

    private HttpResponse<String> post(
            String path, String token, Map<String, Object> body, Duration timeout)
            throws IOException, InterruptedException {

        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(serverUrl + path))
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(
                        MAPPER.writeValueAsString(body), StandardCharsets.UTF_8));
        if (token != null) {
            builder.header("X-Bridge-Token", token);
        }
        return httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }
}
