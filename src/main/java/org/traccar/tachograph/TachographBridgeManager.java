/*
 * Copyright 2026 DH FleetView contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.traccar.tachograph;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.Group;
import org.traccar.model.TachographAudit;
import org.traccar.model.TachographBridge;
import org.traccar.model.User;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.card.CardIdentity;
import org.traccar.tachograph.card.CardIdentityReader;
import org.traccar.tachograph.card.CardUnavailableException;
import org.traccar.tachograph.card.RemoteCardService;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Owns tacho bridges: pairing them, authenticating their heartbeats, tracking whether they and
 * their company card are usable, and reading the card's identity.
 *
 * <p>Pairing works the way a printer or a TV app does. An operator generates a six-digit code in
 * the web app, types it into the bridge, and the bridge exchanges it for a long-lived token. The
 * code is single use, expires in fifteen minutes, and is only ever stored as a hash — as is the
 * token. Neither is ever returned by the API after the moment it is issued.
 */
@Singleton
public class TachographBridgeManager {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographBridgeManager.class);

    private static final int PAIRING_CODE_DIGITS = 6;
    private static final long PAIRING_CODE_TTL_MILLIS = 15 * 60 * 1000L;
    private static final int TOKEN_BYTES = 32;

    private final Config config;
    private final Storage storage;
    private final RemoteCardService cardService;
    private final TachographAuditService auditService;

    private final SecureRandom random = new SecureRandom();

    @Inject
    public TachographBridgeManager(
            Config config,
            Storage storage,
            RemoteCardService cardService,
            TachographAuditService auditService) {
        this.config = config;
        this.storage = storage;
        this.cardService = cardService;
        this.auditService = auditService;
    }

    // -----------------------------------------------------------------------
    // Queries
    // -----------------------------------------------------------------------

    /** Bridges in groups the user can see. An administrator sees every bridge. */
    public List<TachographBridge> list(long userId, boolean administrator) throws StorageException {
        List<TachographBridge> bridges = storage.getObjects(
                TachographBridge.class, new Request(new Columns.All()));

        Set<Long> visibleGroups = administrator ? null : accessibleGroupIds(userId);
        List<TachographBridge> result = new ArrayList<>();
        for (TachographBridge bridge : bridges) {
            if (visibleGroups == null || bridge.getGroupId() == 0 || visibleGroups.contains(bridge.getGroupId())) {
                result.add(refreshLiveness(bridge));
            }
        }
        return result;
    }

    public TachographBridge get(long bridgeId) throws StorageException {
        TachographBridge bridge = storage.getObject(
                TachographBridge.class, new Request(new Columns.All(), new Condition.Equals("id", bridgeId)));
        return bridge != null ? refreshLiveness(bridge) : null;
    }

    /**
     * The bridge that should serve downloads for a group: an online one with a usable card,
     * preferring the group's own bridge over a server-wide one.
     */
    public TachographBridge findAvailable(long groupId) throws StorageException {
        List<TachographBridge> bridges = storage.getObjects(
                TachographBridge.class, new Request(new Columns.All()));

        TachographBridge fallback = null;
        for (TachographBridge bridge : bridges) {
            refreshLiveness(bridge);
            if (!bridge.getCardReady()) {
                continue;
            }
            if (bridge.getGroupId() == groupId) {
                return bridge;
            }
            if (bridge.getGroupId() == 0 && fallback == null) {
                fallback = bridge;
            }
        }
        return fallback;
    }

    /**
     * Marks a bridge offline when its heartbeats have stopped. A bridge that crashed does not
     * get to look available and swallow every download in the fleet.
     */
    private TachographBridge refreshLiveness(TachographBridge bridge) {
        long offlineAfterMillis = config.getInteger(Keys.TACHO_BRIDGE_OFFLINE_AFTER) * 1000L;
        Date lastHeartbeat = bridge.getLastHeartbeat();
        boolean stale = lastHeartbeat == null
                || System.currentTimeMillis() - lastHeartbeat.getTime() > offlineAfterMillis;
        if (stale && TachographBridge.STATUS_ONLINE.equals(bridge.getStatus())) {
            bridge.setStatus(TachographBridge.STATUS_OFFLINE);
        }
        return bridge;
    }

    // -----------------------------------------------------------------------
    // Pairing
    // -----------------------------------------------------------------------

    /**
     * Creates a bridge record holding a one-time pairing code.
     *
     * @return the bridge, carrying the plaintext code in its transient pairing-code field
     */
    public TachographBridge createPairingCode(long groupId, String name, long userId) throws StorageException {
        String code = generatePairingCode();

        TachographBridge bridge = new TachographBridge();
        bridge.setBridgeId("pending-" + java.util.UUID.randomUUID());
        bridge.setGroupId(groupId);
        bridge.setName(name != null && !name.isBlank() ? name : "Tacho Bridge");
        bridge.setStatus(TachographBridge.STATUS_OFFLINE);
        bridge.setReaderStatus(TachographBridge.READER_NO_READER);
        bridge.setCardStatus(TachographBridge.READER_NO_CARD);
        bridge.setPairingCodeHash(hash(code));
        bridge.setPairingCodeExpiresAt(new Date(System.currentTimeMillis() + PAIRING_CODE_TTL_MILLIS));
        bridge.setRegisteredAt(new Date());

        long id = storage.addObject(bridge, new Request(new Columns.Exclude("id")));
        bridge.setId(id);
        bridge.setPairingCode(code);

        auditService.record(userId, 0, TachographAudit.ACTION_BRIDGE_PAIRED,
                "Pairing code generated for group " + groupId);
        LOGGER.info("Generated a tacho bridge pairing code for group {}", groupId);
        return bridge;
    }

    /**
     * Exchanges a pairing code for a bridge token.
     *
     * @return the bridge, carrying the plaintext token in its transient bridge-token field
     */
    public synchronized TachographBridge register(
            String pairingCode, String bridgeId, String name, String softwareVersion, String hostname)
            throws StorageException, TachographException {

        if (pairingCode == null || bridgeId == null || bridgeId.isBlank()) {
            throw new TachographException(
                    "TACHO_INVALID_PAIRING", "A pairing code and a bridge identifier are required");
        }

        String codeHash = hash(pairingCode);
        Date now = new Date();

        TachographBridge matched = null;
        for (TachographBridge candidate : storage.getObjects(
                TachographBridge.class, new Request(new Columns.All()))) {
            if (candidate.getPairingCodeHash() != null
                    && constantTimeEquals(codeHash, candidate.getPairingCodeHash())
                    && candidate.getPairingCodeExpiresAt() != null
                    && candidate.getPairingCodeExpiresAt().after(now)) {
                matched = candidate;
                break;
            }
        }
        if (matched == null) {
            LOGGER.warn("Rejected a tacho bridge registration with an invalid or expired pairing code");
            throw new TachographException(
                    "TACHO_INVALID_PAIRING", "That pairing code is not valid or has expired");
        }

        String token = generateToken();

        matched.setBridgeId(bridgeId);
        if (name != null && !name.isBlank()) {
            matched.setName(name);
        }
        matched.setSoftwareVersion(softwareVersion);
        matched.setHostname(hostname);
        matched.setStatus(TachographBridge.STATUS_ONLINE);
        matched.setTokenHash(hash(token));
        matched.setRegisteredAt(now);
        matched.setLastSeenAt(now);
        matched.setLastHeartbeat(now);
        // The code is single use: burn it whether or not anything else changes.
        matched.setPairingCodeHash(null);
        matched.setPairingCodeExpiresAt(null);

        storage.updateObject(matched,

                new Request(new Columns.Exclude("id"), new Condition.Equals("id", matched.getId())));

        matched.setBridgeToken(token);
        auditService.recordSystem(0, TachographAudit.ACTION_BRIDGE_PAIRED,
                "Bridge " + bridgeId + " registered for group " + matched.getGroupId(), bridgeId);
        LOGGER.info("Tacho bridge {} registered for group {}", bridgeId, matched.getGroupId());
        return matched;
    }

    /** Removes a bridge and drops any card work queued for it. */
    public void delete(long bridgeId, long userId) throws StorageException {
        TachographBridge bridge = get(bridgeId);
        if (bridge == null) {
            return;
        }
        cardService.purge(bridgeId);
        storage.removeObject(TachographBridge.class, new Request(new Condition.Equals("id", bridgeId)));
        auditService.record(userId, 0, TachographAudit.ACTION_BRIDGE_REMOVED,
                "Bridge " + bridge.getBridgeId() + " removed");
        LOGGER.info("Tacho bridge {} removed", bridge.getBridgeId());
    }

    // -----------------------------------------------------------------------
    // Bridge authentication
    // -----------------------------------------------------------------------

    /**
     * Resolves a bridge from its token.
     *
     * @throws TachographException when the token does not match the identified bridge
     */
    public TachographBridge authenticate(long bridgeId, String token)
            throws StorageException, TachographException {

        TachographBridge bridge = storage.getObject(
                TachographBridge.class, new Request(new Columns.All(), new Condition.Equals("id", bridgeId)));
        if (bridge == null || bridge.getTokenHash() == null) {
            throw new TachographException("TACHO_UNAUTHORIZED", "Unknown bridge");
        }
        if (token == null || !constantTimeEquals(hash(token), bridge.getTokenHash())) {
            LOGGER.warn("Rejected a heartbeat for bridge {} with an invalid token", bridgeId);
            throw new TachographException("TACHO_UNAUTHORIZED", "Invalid bridge token");
        }
        return bridge;
    }

    /**
     * Records a heartbeat and returns what the bridge should know.
     *
     * @param body the reported reader status, card status, software version and host name
     */
    public Map<String, Object> heartbeat(TachographBridge bridge, Map<String, Object> body)
            throws StorageException {

        Date now = new Date();
        bridge.setLastHeartbeat(now);
        bridge.setLastSeenAt(now);
        bridge.setStatus(TachographBridge.STATUS_ONLINE);

        if (body != null) {
            applyString(body.get("readerStatus"), bridge::setReaderStatus);
            applyString(body.get("cardStatus"), bridge::setCardStatus);
            applyString(body.get("softwareVersion"), bridge::setSoftwareVersion);
            applyString(body.get("hostname"), bridge::setHostname);
        }

        // A card that has been taken out invalidates whatever identity we had cached for it.
        if (TachographBridge.READER_NO_CARD.equals(bridge.getCardStatus())
                || TachographBridge.READER_CARD_REMOVED.equals(bridge.getCardStatus())) {
            bridge.setCardIdentifier(null);
            bridge.setCardHolder(null);
            bridge.setCardValidityTo(null);
            bridge.setCardValidityFrom(null);
            bridge.setCardCheckedAt(null);
        }

        storage.updateObject(bridge,

                new Request(new Columns.Exclude("id"), new Condition.Equals("id", bridge.getId())));

        long pollSeconds = config.getInteger(Keys.TACHO_CARD_POLL_TIMEOUT);
        Long holdingJob = cardService.getHoldingJob(bridge.getId());
        return Map.of(
                "status", "ok",
                "pollTimeoutSeconds", pollSeconds,
                "cardInUse", holdingJob != null,
                "serverTime", now.getTime());
    }

    // -----------------------------------------------------------------------
    // Company card identity
    // -----------------------------------------------------------------------

    /**
     * Reads the company card's identity through the bridge and stores it, so the operator can
     * see which card is fitted and be warned before it expires.
     *
     * @return the identity read from the card
     */
    public CardIdentity readCardIdentity(long bridgeId, long userId)
            throws StorageException, TachographException {

        TachographBridge bridge = get(bridgeId);
        if (bridge == null) {
            throw new TachographException("TACHO_NOT_FOUND", "Bridge not found: " + bridgeId);
        }
        if (!TachographBridge.STATUS_ONLINE.equals(bridge.getStatus())) {
            throw new TachographException(
                    TachographException.BRIDGE_UNAVAILABLE, "Bridge " + bridge.getName() + " is offline");
        }

        String session = null;
        try {
            session = cardService.openSession(
                    bridgeId, 0, config.getInteger(Keys.TACHO_AUTH_TIMEOUT));
            CardIdentity identity = CardIdentityReader.read(cardService, session);

            bridge.setCardIdentifier(identity.getCardNumber());
            bridge.setCardHolder(identity.getCompanyName());
            bridge.setCardIssuer(identity.getIssuingAuthority());
            bridge.setCardValidityFrom(identity.getValidityBegin());
            bridge.setCardValidityTo(identity.getExpiryDate());
            bridge.setCardType("COMPANY");
            bridge.setCardCheckedAt(new Date());
            bridge.setCardCheckError(null);
            storage.updateObject(bridge,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", bridgeId)));

            auditService.record(userId, 0, TachographAudit.ACTION_CARD_READ,
                    "Company card " + identity.getCardNumber() + " read on bridge " + bridge.getName());
            LOGGER.info("Read company card {} on bridge {}", identity.getCardNumber(), bridge.getName());
            return identity;

        } catch (CardUnavailableException e) {
            bridge.setCardCheckError(e.getMessage());
            bridge.setCardCheckedAt(new Date());
            storage.updateObject(bridge,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", bridgeId)));
            throw new TachographException(TachographException.CARD_UNAVAILABLE, e.getMessage(), e);
        } finally {
            if (session != null) {
                cardService.closeSession(session);
            }
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private Set<Long> accessibleGroupIds(long userId) throws StorageException {
        Set<Long> ids = new HashSet<>();
        for (Group group : storage.getObjects(Group.class, new Request(
                new Columns.Include("id"),
                new Condition.Permission(User.class, userId, Group.class)))) {
            ids.add(group.getId());
        }
        return ids;
    }

    private void applyString(Object value, java.util.function.Consumer<String> setter) {
        if (value != null) {
            String text = value.toString().trim();
            if (!text.isEmpty()) {
                setter.accept(text);
            }
        }
    }

    private String generatePairingCode() {
        int bound = (int) Math.pow(10, PAIRING_CODE_DIGITS);
        return String.format("%0" + PAIRING_CODE_DIGITS + "d", random.nextInt(bound));
    }

    private String generateToken() {
        byte[] bytes = new byte[TOKEN_BYTES];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String hash(String input) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                builder.append(String.format("%02x", b));
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    /** Compares two hex digests without leaking their difference through timing. */
    private boolean constantTimeEquals(String left, String right) {
        if (left == null || right == null) {
            return false;
        }
        return MessageDigest.isEqual(
                left.getBytes(StandardCharsets.UTF_8), right.getBytes(StandardCharsets.UTF_8));
    }
}
