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
import org.traccar.model.TachographBridge;
import org.traccar.storage.StorageException;
import org.traccar.tachograph.card.CardIdentity;
import org.traccar.tachograph.card.CardIdentityReader;
import org.traccar.tachograph.card.CardUnavailableException;
import org.traccar.tachograph.card.RemoteCardService;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Company-card authentication backed by a real card in a tacho bridge.
 *
 * <p>The important thing this class does <em>not</em> do is cryptography. In a remote download
 * the vehicle unit and the company card authenticate each other directly; the server is a wire
 * between them, relaying command and response bytes it does not interpret and for which it holds
 * no keys. That is what makes the whole feature possible without card secrets ever leaving the
 * office reader.
 *
 * <p>What it does do is make sure that wire is worth building before a download starts: that a
 * bridge is online, that a company card is actually in its reader, that the card answers, and
 * that it has not expired. Catching an expired card here costs a second; discovering it half an
 * hour into a transfer costs the whole transfer, and quietly stalls every scheduled download in
 * the fleet until somebody notices.
 */
@Singleton
public class BridgeAuthenticationProvider implements TachographAuthenticationProvider {

    private static final Logger LOGGER = LoggerFactory.getLogger(BridgeAuthenticationProvider.class);

    /** How close to expiry a company card gets a warning rather than silence. */
    private static final int EXPIRY_WARNING_DAYS = 30;

    private final Config config;
    private final TachographBridgeManager bridgeManager;
    private final RemoteCardService cardService;

    private final Map<String, Long> bridgeBySession = new ConcurrentHashMap<>();

    @Inject
    public BridgeAuthenticationProvider(
            Config config,
            TachographBridgeManager bridgeManager,
            RemoteCardService cardService) {
        this.config = config;
        this.bridgeManager = bridgeManager;
        this.cardService = cardService;
    }

    @Override
    public boolean isAvailable(long groupId) {
        try {
            return bridgeManager.findAvailable(groupId) != null;
        } catch (StorageException e) {
            LOGGER.warn("Could not look for an available tacho bridge for group {}", groupId, e);
            return false;
        }
    }

    @Override
    public BridgeStatusInfo getStatus(long groupId) {
        try {
            TachographBridge bridge = bridgeManager.findAvailable(groupId);
            if (bridge == null) {
                return null;
            }
            BridgeStatusInfo info = new BridgeStatusInfo();
            info.setBridgeId(bridge.getBridgeId());
            info.setBridgeStatus(TachographBridge.STATUS_ONLINE.equals(bridge.getStatus())
                    ? BridgeStatus.ONLINE : BridgeStatus.OFFLINE);
            info.setReaderStatus(bridge.getReaderStatus());
            info.setCardStatus(bridge.getCardStatus());
            info.setSoftwareVersion(bridge.getSoftwareVersion());
            info.setLastHeartbeat(bridge.getLastHeartbeat());

            CardMetadata metadata = new CardMetadata();
            metadata.setCardIdentifier(bridge.getCardIdentifier());
            metadata.setCardType(bridge.getCardType());
            metadata.setIssuingAuthority(bridge.getCardIssuer());
            metadata.setValidityTo(bridge.getCardValidityTo());
            metadata.setStatus(bridge.getCardStatus());
            info.setCardMetadata(metadata);
            return info;
        } catch (StorageException e) {
            LOGGER.warn("Could not read tacho bridge status for group {}", groupId, e);
            return null;
        }
    }

    @Override
    public String createSession(long downloadJobId, long groupId) throws TachographException {
        TachographBridge bridge;
        try {
            bridge = bridgeManager.findAvailable(groupId);
        } catch (StorageException e) {
            throw new TachographException(
                    TachographException.BRIDGE_UNAVAILABLE,
                    "Could not look for a tacho bridge: " + e.getMessage(), e);
        }

        if (bridge == null) {
            throw new TachographException(
                    TachographException.BRIDGE_UNAVAILABLE,
                    "No tacho bridge with a company card is available for group " + groupId
                            + ". Check that the bridge application is running and the card is inserted.");
        }

        try {
            String token = cardService.openSession(
                    bridge.getId(), downloadJobId, config.getInteger(Keys.TACHO_DOWNLOAD_TIMEOUT));
            bridgeBySession.put(token, bridge.getId());
            LOGGER.info("Download job {} took the company card on bridge {}",
                    downloadJobId, bridge.getName());
            return token;
        } catch (CardUnavailableException e) {
            throw new TachographException(TachographException.CARD_UNAVAILABLE, e.getMessage(), e);
        }
    }

    @Override
    public void authenticate(String sessionToken, long downloadJobId) throws TachographException {
        try {
            CardIdentity identity = CardIdentityReader.read(cardService, sessionToken);

            if (identity.isExpired()) {
                throw new TachographException(
                        TachographException.CARD_LOCKED, String.format(
                                "The company card %s is outside its validity period and cannot "
                                        + "authorise a download. Replace it before retrying.",
                                identity.getCardNumber()));
            }

            Long daysLeft = identity.getDaysUntilExpiry();
            if (daysLeft != null && daysLeft <= EXPIRY_WARNING_DAYS) {
                LOGGER.warn("Company card {} expires in {} day(s); order a replacement before "
                        + "downloads start failing", identity.getCardNumber(), daysLeft);
            }

            LOGGER.info("Download job {} authenticated with company card {}",
                    downloadJobId, identity.getCardNumber());

        } catch (CardUnavailableException e) {
            throw new TachographException(TachographException.AUTHENTICATION_FAILED, e.getMessage(), e);
        }
    }

    @Override
    public void closeSession(String sessionToken) {
        if (sessionToken != null) {
            cardService.closeSession(sessionToken);
            bridgeBySession.remove(sessionToken);
        }
    }

    @Override
    public long getBridgeId(String sessionToken) {
        return bridgeBySession.getOrDefault(sessionToken, 0L);
    }
}
