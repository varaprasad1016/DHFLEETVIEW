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

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Mock authentication provider for simulator/testing ONLY.
 * TEST ONLY - NOT FOR PRODUCTION.
 */
@Singleton
public class MockAuthenticationProvider implements TachographAuthenticationProvider {

    private static final Logger LOGGER = LoggerFactory.getLogger(MockAuthenticationProvider.class);

    private final Config config;
    private final Map<String, String> sessions = new ConcurrentHashMap<>();

    @Inject
    public MockAuthenticationProvider(Config config) {
        this.config = config;
    }

    @Override
    public boolean isAvailable(long groupId) {
        return Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_ENABLED))
                && Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_SIMULATOR));
    }

    @Override
    public BridgeStatusInfo getStatus(long groupId) {
        if (!isAvailable(groupId)) {
            return null;
        }
        BridgeStatusInfo info = new BridgeStatusInfo();
        info.setBridgeId("mock-bridge-" + groupId);
        info.setBridgeStatus(BridgeStatus.ONLINE);
        info.setReaderStatus("READER_CONNECTED");
        info.setCardStatus(CardStatus.CARD_READY.name());
        info.setSoftwareVersion("mock-1.0");
        info.setLastHeartbeat(new java.util.Date());

        CardMetadata metadata = new CardMetadata();
        metadata.setCardIdentifier("MOCK_CARD_" + groupId);
        metadata.setCardType("COMPANY_CARD");
        metadata.setStatus("VALID");
        info.setCardMetadata(metadata);
        return info;
    }

    @Override
    public String createSession(long downloadJobId, long groupId) throws TachographException {
        if (!isAvailable(groupId)) {
            throw new TachographException(
                    TachographException.CARD_UNAVAILABLE, "No mock card available for group " + groupId);
        }
        String token = UUID.randomUUID().toString();
        sessions.put(token, String.valueOf(downloadJobId));
        LOGGER.info("Mock auth session {} created for job {} group {}", token, downloadJobId, groupId);
        return token;
    }

    @Override
    public void authenticate(String sessionToken, long downloadJobId) throws TachographException {
        if (!sessions.containsKey(sessionToken)) {
            throw new TachographException(
                    TachographException.AUTHENTICATION_FAILED, "Invalid mock session " + sessionToken);
        }
        // Simulate a short card interaction; no real cryptography is performed.
        try {
            Thread.sleep(200);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        LOGGER.info("Mock authentication succeeded for job {} session {}", downloadJobId, sessionToken);
    }

    @Override
    public void closeSession(String sessionToken) {
        sessions.remove(sessionToken);
        LOGGER.info("Mock auth session {} closed", sessionToken);
    }
}
