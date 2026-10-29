package com.dhfleetview.bridge;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * The DH FleetView Tacho Bridge.
 *
 * <p>Runs on an office machine that has the company tachograph card in a card reader, and makes
 * that card reachable to the fleet server so vehicles can be downloaded remotely. Without it,
 * every download means physically taking the card to the vehicle.
 *
 * <p>What it actually does is narrow on purpose: it relays command bytes to the card and relays
 * the answers back. It never sees a key, never decides whether an authentication succeeded, and
 * never holds fleet data. The card's secrets stay inside the card, which is the only place they
 * are allowed to be.
 *
 * <p>Usage:
 * <pre>
 *   java -jar tacho-bridge.jar pair 123456   pair with a code from the web app
 *   java -jar tacho-bridge.jar               run
 * </pre>
 * Configuration lives in {@code bridge.properties} beside the JAR.
 */
public final class Main {

    private static final Logger LOGGER = LoggerFactory.getLogger(Main.class);

    public static final String SOFTWARE_VERSION = "2.0.0";

    private static final int HEARTBEAT_SECONDS = 30;
    private static final int STATUS_PORT = 8765;

    /** How long to wait after a failed poll before trying again, so a broken link does not spin. */
    private static final long POLL_BACKOFF_MILLIS = 5000;

    private final BridgeConfig config;
    private final SmartCardReader reader;
    private final ServerClient client;

    private volatile String lastError;

    private Main(BridgeConfig config, SmartCardReader reader) {
        this.config = config;
        this.reader = reader;
        this.client = new ServerClient(config.getServerUrl());
    }

    public static void main(String[] args) throws Exception {
        BridgeConfig config = BridgeConfig.load();
        SmartCardReader reader = openReader();
        Main bridge = new Main(config, reader);

        if (args.length > 1 && "pair".equalsIgnoreCase(args[0])) {
            bridge.pair(args[1]);
            return;
        }
        if (args.length > 0 && "pair".equalsIgnoreCase(args[0])) {
            System.err.println("Usage: java -jar tacho-bridge.jar pair <PAIRING_CODE>");
            System.exit(2);
        }

        if (config.getBridgeToken() == null || config.getBridgeNumericId() == null) {
            System.out.println("This bridge is not paired yet.");
            System.out.println("In the web app open Tachograph, then Bridges, then Generate Pairing Code,");
            System.out.println("and run: java -jar tacho-bridge.jar pair <CODE>");
            return;
        }

        bridge.run();
    }

    /** Opens the real reader, falling back to the mock only when explicitly asked. */
    private static SmartCardReader openReader() {
        boolean mock = "mock".equalsIgnoreCase(System.getProperty("tacho.reader", "pcsc"));
        SmartCardReader reader = mock ? new MockSmartCardReader() : new PcscSmartCardReader();
        try {
            reader.connect();
        } catch (Exception e) {
            // A reader that is unplugged now may be plugged in later, so this is not fatal: the
            // bridge stays up, reports NO_READER in its heartbeat, and the web app shows why
            // downloads are not running.
            LOGGER.warn("No card reader available yet: {}", e.getMessage());
        }
        return reader;
    }

    // -----------------------------------------------------------------------
    // Pairing
    // -----------------------------------------------------------------------

    private void pair(String pairingCode) throws Exception {
        String bridgeId = config.getBridgeId();
        if (bridgeId == null) {
            bridgeId = UUID.randomUUID().toString();
            config.setBridgeId(bridgeId);
        }

        ServerClient.Registration registration = client.register(
                pairingCode, bridgeId, config.getBridgeName(), SOFTWARE_VERSION, hostname());

        config.setBridgeNumericId(registration.getNumericId());
        config.setBridgeToken(registration.getToken());
        config.setBridgeName(registration.getName());
        config.save();

        System.out.println("Paired successfully as \"" + registration.getName() + "\".");
        System.out.println("Start the bridge with: java -jar tacho-bridge.jar");
        LOGGER.info("Paired with the server as bridge {}", registration.getNumericId());
    }

    // -----------------------------------------------------------------------
    // Running
    // -----------------------------------------------------------------------

    private void run() throws Exception {
        LOGGER.info("Tacho Bridge {} starting, server {}", SOFTWARE_VERSION, config.getServerUrl());

        startHeartbeat();
        startCardRelay();
        startStatusServer();

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                reader.disconnect();
            } catch (Exception ignored) {
                // Shutting down anyway.
            }
        }));

        Thread.currentThread().join();
    }

    private void startHeartbeat() {
        ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "tacho-heartbeat");
            thread.setDaemon(true);
            return thread;
        });
        scheduler.scheduleAtFixedRate(() -> {
            try {
                client.heartbeat(
                        config.getBridgeNumericId(), config.getBridgeToken(),
                        reader.getReaderStatus().name(), reader.getCardStatus().name(),
                        SOFTWARE_VERSION, hostname());
                lastError = null;
            } catch (Exception e) {
                lastError = e.getMessage();
                LOGGER.warn("Heartbeat failed: {}", e.getMessage());
            }
        }, 0, HEARTBEAT_SECONDS, TimeUnit.SECONDS);
    }

    /**
     * The relay loop: ask the server for card work, run it, send the answer back.
     *
     * <p>This is the whole reason the bridge exists. A vehicle unit half a country away is
     * mid-authentication with this card, and every round trip through here is one step of that
     * exchange, so the loop stays running whatever happens to any individual command.
     */
    private void startCardRelay() {
        Thread thread = new Thread(() -> {
            while (true) {
                try {
                    ServerClient.CardTask task = client.pollCard(
                            config.getBridgeNumericId(), config.getBridgeToken());
                    if (task != null) {
                        handleCardTask(task);
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                } catch (Exception e) {
                    LOGGER.warn("Card relay poll failed: {}", e.getMessage());
                    sleep(POLL_BACKOFF_MILLIS);
                }
            }
        }, "tacho-card-relay");
        thread.setDaemon(true);
        thread.start();
    }

    private void handleCardTask(ServerClient.CardTask task) {
        String errorCode = null;
        String errorMessage = null;
        byte[] response = new byte[0];

        try {
            switch (task.getType()) {
                case "TRANSMIT" -> {
                    if (!reader.isCardPresent()) {
                        errorCode = "TACHO_CARD_UNAVAILABLE";
                        errorMessage = "No card is present in the reader";
                    } else {
                        // The payload is card protocol data. It is never logged: an
                        // authentication exchange carries challenge and cryptogram material.
                        response = reader.transmit(task.getData());
                    }
                }
                case "RESET" -> {
                    reader.disconnect();
                    reader.connect();
                    response = new byte[0];
                }
                default -> {
                    errorCode = "TACHO_UNSUPPORTED_COMMAND";
                    errorMessage = "Unsupported command: " + task.getType();
                }
            }
        } catch (Exception e) {
            errorCode = "TACHO_CARD_ERROR";
            errorMessage = e.getMessage();
            LOGGER.warn("Card command {} failed: {}", task.getCommandId(), e.getMessage());
        }

        try {
            client.respondCard(
                    config.getBridgeNumericId(), config.getBridgeToken(),
                    task.getCommandId(), response, errorCode, errorMessage);
        } catch (Exception e) {
            LOGGER.warn("Could not return the answer for card command {}: {}",
                    task.getCommandId(), e.getMessage());
        }
    }

    /**
     * A diagnostics endpoint on the loopback interface only, so an engineer on the machine can
     * see what the bridge thinks is going on without opening anything to the network.
     */
    private void startStatusServer() {
        try {
            com.sun.net.httpserver.HttpServer server = com.sun.net.httpserver.HttpServer.create(
                    new InetSocketAddress(InetAddress.getLoopbackAddress(), STATUS_PORT), 0);

            server.createContext("/status", exchange -> {
                String json = String.format(
                        "{\"version\":\"%s\",\"server\":\"%s\",\"bridgeId\":\"%s\",\"paired\":%s,"
                                + "\"reader\":\"%s\",\"card\":\"%s\",\"lastError\":%s}",
                        SOFTWARE_VERSION, config.getServerUrl(), config.getBridgeId(),
                        config.getBridgeToken() != null,
                        reader.getReaderStatus(), reader.getCardStatus(),
                        lastError == null ? "null" : "\"" + lastError.replace("\"", "'") + "\"");

                byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, bytes.length);
                try (var out = exchange.getResponseBody()) {
                    out.write(bytes);
                }
            });

            server.setExecutor(Executors.newSingleThreadExecutor());
            server.start();
            LOGGER.info("Diagnostics available at http://127.0.0.1:{}/status", STATUS_PORT);
        } catch (IOException e) {
            LOGGER.warn("Could not start the local status server: {}", e.getMessage());
        }
    }

    private String hostname() {
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (Exception e) {
            return "unknown";
        }
    }

    private void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
