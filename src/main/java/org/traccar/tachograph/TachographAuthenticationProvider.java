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

import java.util.Date;

/**
 * Company-card authentication for remote tachograph downloads.
 *
 * <p>Two implementations exist: {@link BridgeAuthenticationProvider}, which uses a real card in a
 * tacho bridge, and {@link MockAuthenticationProvider}, which stands in for one while the
 * simulator is running.
 */
public interface TachographAuthenticationProvider {

    /** State of the card in a bridge's reader. */
    enum CardStatus {
        NO_READER,
        READER_CONNECTED,
        NO_CARD,
        CARD_INSERTED,
        CARD_READY,
        CARD_ERROR,
        CARD_REMOVED
    }

    /** Whether a bridge is currently reachable. */
    enum BridgeStatus {
        ONLINE,
        OFFLINE
    }

    /** What a company card says about itself. */
    class CardMetadata {

        private String cardIdentifier;
        private String cardType;
        private String issuingAuthority;
        private Date validityTo;
        private String status;

        public String getCardIdentifier() {
            return cardIdentifier;
        }

        public void setCardIdentifier(String cardIdentifier) {
            this.cardIdentifier = cardIdentifier;
        }

        public String getCardType() {
            return cardType;
        }

        public void setCardType(String cardType) {
            this.cardType = cardType;
        }

        public String getIssuingAuthority() {
            return issuingAuthority;
        }

        public void setIssuingAuthority(String issuingAuthority) {
            this.issuingAuthority = issuingAuthority;
        }

        public Date getValidityTo() {
            return validityTo;
        }

        public void setValidityTo(Date validityTo) {
            this.validityTo = validityTo;
        }

        public String getStatus() {
            return status;
        }

        public void setStatus(String status) {
            this.status = status;
        }
    }

    /** A snapshot of a bridge and the card in it. */
    class BridgeStatusInfo {

        private String bridgeId;
        private BridgeStatus bridgeStatus;
        private String readerStatus;
        private String cardStatus;
        private CardMetadata cardMetadata;
        private String softwareVersion;
        private Date lastHeartbeat;

        public String getBridgeId() {
            return bridgeId;
        }

        public void setBridgeId(String bridgeId) {
            this.bridgeId = bridgeId;
        }

        public BridgeStatus getBridgeStatus() {
            return bridgeStatus;
        }

        public void setBridgeStatus(BridgeStatus bridgeStatus) {
            this.bridgeStatus = bridgeStatus;
        }

        public String getReaderStatus() {
            return readerStatus;
        }

        public void setReaderStatus(String readerStatus) {
            this.readerStatus = readerStatus;
        }

        public String getCardStatus() {
            return cardStatus;
        }

        public void setCardStatus(String cardStatus) {
            this.cardStatus = cardStatus;
        }

        public CardMetadata getCardMetadata() {
            return cardMetadata;
        }

        public void setCardMetadata(CardMetadata cardMetadata) {
            this.cardMetadata = cardMetadata;
        }

        public String getSoftwareVersion() {
            return softwareVersion;
        }

        public void setSoftwareVersion(String softwareVersion) {
            this.softwareVersion = softwareVersion;
        }

        public Date getLastHeartbeat() {
            return lastHeartbeat;
        }

        public void setLastHeartbeat(Date lastHeartbeat) {
            this.lastHeartbeat = lastHeartbeat;
        }
    }

    /** Whether a bridge with a usable card is available for the given group. */
    boolean isAvailable(long groupId);

    /** The current bridge and card state for a group, or null when none is available. */
    BridgeStatusInfo getStatus(long groupId);

    /**
     * Takes exclusive use of the company card for one download.
     *
     * @return an opaque session token
     * @throws TachographException when no bridge or card is available
     */
    String createSession(long downloadJobId, long groupId) throws TachographException;

    /**
     * Confirms the card is present, responding and within its validity period, before a download
     * commits to a long transfer.
     */
    void authenticate(String sessionToken, long downloadJobId) throws TachographException;

    /** Releases the card. */
    void closeSession(String sessionToken);

    /**
     * The bridge holding the card for a session, or zero when the session is not backed by one.
     * Recorded against the download job so an operator can see which card authorised it.
     */
    default long getBridgeId(String sessionToken) {
        return 0;
    }
}
