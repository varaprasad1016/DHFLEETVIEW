/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.tachograph;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.TachographDownloadJob;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Date;

/**
 * Simulated FMC650 client for development/testing ONLY.
 * TEST ONLY - NOT FOR PRODUCTION.
 *
 * <p>Generates small synthetic DDD files with deterministic content. The files are valid
 * for end-to-end testing (transfer, SHA-256, storage, download) but are NOT real
 * tachograph data and will not parse as compliant DDD in a real tacho parser.
 */
@Singleton
public class SimulatedTachographDeviceClient implements TachographDeviceClient {

    private static final Logger LOGGER = LoggerFactory.getLogger(SimulatedTachographDeviceClient.class);

    public static final String MARKER = "SIMULATED_DDD_FILE_FOR_TESTING_ONLY";

    private final Config config;
    private final SecureRandom random = new SecureRandom();

    public enum SimulatedBehaviour {
        SUCCESS,
        OFFLINE,
        TIMEOUT,
        INVALID_FILE,
        DEVICE_ERROR
    }

    @Inject
    public SimulatedTachographDeviceClient(Config config) {
        this.config = config;
    }

    @Override
    public String getClientType() {
        return CLIENT_SIMULATED;
    }

    @Override
    public boolean canHandle(long deviceId) {
        return Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_SIMULATOR));
    }

    @Override
    public TachographDownloadResult download(long deviceId, String downloadType) throws TachographException {
        SimulatedBehaviour behaviour = resolveBehaviour(downloadType);
        LOGGER.info("Simulated download for device {} type {} behaviour {}", deviceId, downloadType, behaviour);
        switch (behaviour) {
            case OFFLINE -> throw new TachographException(
                    TachographException.DEVICE_OFFLINE, "Simulated device offline");
            case TIMEOUT -> throw new TachographException(
                    TachographException.DOWNLOAD_TIMEOUT, "Simulated download timeout");
            case DEVICE_ERROR -> throw new TachographException(
                    TachographException.PROTOCOL_ERROR, "Simulated device protocol error");
            case INVALID_FILE -> {
                byte[] data = "INVALID_DDD_CONTENT".getBytes(StandardCharsets.UTF_8);
                String name = buildFileName(deviceId, downloadType, new Date()) + "_INVALID.DDD";
                return new TachographDownloadResult(data, name, downloadType, new Date());
            }
            default -> {
                // SUCCESS
                try {
                    Thread.sleep(800 + random.nextInt(700));
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                byte[] data = buildDddBytes(deviceId, downloadType);
                String name = buildFileName(deviceId, downloadType, new Date());
                return new TachographDownloadResult(data, name, downloadType, new Date());
            }
        }
    }

    private SimulatedBehaviour resolveBehaviour(String downloadType) {
        // Deterministic hook for tests: attribute-driven tests can set tacho.simulator.behaviour
        // via system property. Default is SUCCESS.
        String prop = System.getProperty("tacho.simulator.behaviour");
        if (prop != null) {
            try {
                return SimulatedBehaviour.valueOf(prop.trim().toUpperCase());
            } catch (IllegalArgumentException ignored) {
                // fall through
            }
        }
        return SimulatedBehaviour.SUCCESS;
    }

    private byte[] buildDddBytes(long deviceId, String downloadType) {
        String header = MARKER + "\n"
                + "deviceId=" + deviceId + "\n"
                + "type=" + downloadType + "\n"
                + "generated=" + new Date() + "\n"
                + "NOTE: This file is synthetic and not a real DDD file.\n";
        byte[] headerBytes = header.getBytes(StandardCharsets.UTF_8);
        byte[] payload = new byte[2048 + random.nextInt(1024)];
        random.nextBytes(payload);
        byte[] result = new byte[headerBytes.length + payload.length];
        System.arraycopy(headerBytes, 0, result, 0, headerBytes.length);
        System.arraycopy(payload, 0, result, headerBytes.length, payload.length);
        return result;
    }

    private String buildFileName(long deviceId, String downloadType, Date now) {
        String typePrefix = TachographDownloadJob.TYPE_DRIVER.equals(downloadType) ? "C" : "M";
        String ts = String.format("%tY%<tm%<td%<tH%<tM%<tS", now);
        return String.format("%s_%s_%d.DDD", typePrefix, ts, deviceId);
    }
}
