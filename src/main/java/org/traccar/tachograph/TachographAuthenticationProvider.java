/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.tachograph;

/**
 * Abstraction for company-card authentication required for remote tachograph downloads.
 * Production implementation requires a physical smart-card via a Tacho Bridge.
 * See docs/tachograph/TACHO-BRIDGE.md.
 */
public interface TachographAuthenticationProvider {

    enum CardStatus {
        NO_READER,
        READER_CONNECTED,
        NO_CARD,
        CARD_INSERTED,
        CARD_READY,
        CARD_ERROR,
        CARD_REMOVED
    }

    enum BridgeStatus {
        ONLINE,
        OFFLINE
    }

    class CardMetadata {
        public String cardIdentifier;
        public String cardType;
        public String issuingAuthority;
        public java.util.Date validityTo;
        public String status;
    }

    class BridgeStatusInfo {
        public String bridgeId;
        public BridgeStatus bridgeStatus;
        public String readerStatus;
        public String cardStatus;
        public CardMetadata cardMetadata;
        public String softwareVersion;
        public java.util.Date lastHeartbeat;
    }

    /**
     * Returns whether a bridge/card is available for the given group. For the mock
     * provider this always returns true when simulator mode is enabled.
     */
    boolean isAvailable(long groupId);

    /**
     * Returns the current bridge+card status for the given group, or null when unavailable.
     */
    BridgeStatusInfo getStatus(long groupId);

    /**
     * Creates an authentication session for the given download job. The session represents
     * an exclusive lock on the company card.
     *
     * @return opaque session token, or null when no card is available
     * @throws TachographException with error codes like TACHO_BRIDGE_UNAVAILABLE, TACHO_CARD_UNAVAILABLE
     */
    String createSession(long downloadJobId, long groupId) throws TachographException;

    /**
     * Performs the card authentication operation. For the mock provider this is a no-op
     * that succeeds after a short delay.
     */
    void authenticate(String sessionToken, long downloadJobId) throws TachographException;

    /**
     * Closes the authentication session and releases the card lock.
     */
    void closeSession(String sessionToken);
}
