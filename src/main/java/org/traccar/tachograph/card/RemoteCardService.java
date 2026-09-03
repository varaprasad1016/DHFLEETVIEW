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
package org.traccar.tachograph.card;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.Date;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * Routes card commands between a download in progress and the bridge that holds the company card.
 *
 * <p>The bridge never accepts inbound connections. It long-polls {@link #poll} for the next
 * command, executes it against the physical reader and posts the answer to {@link #complete}.
 * The download worker calls {@link #submit} and blocks on the round trip.
 *
 * <p>A company card can serve one authentication at a time, so a bridge holds at most one open
 * session. {@link #openSession} refuses a second one rather than interleaving commands, which a
 * smart card's stateful security context would not survive.
 */
@Singleton
public class RemoteCardService {

    private static final Logger LOGGER = LoggerFactory.getLogger(RemoteCardService.class);

    /** State of one exclusive hold on a bridge's card. */
    private static final class Session {
        private final long bridgeId;
        private final long downloadJobId;
        private final Date openedAt = new Date();
        private volatile Date expiresAt;

        private Session(long bridgeId, long downloadJobId, Date expiresAt) {
            this.bridgeId = bridgeId;
            this.downloadJobId = downloadJobId;
            this.expiresAt = expiresAt;
        }
    }

    private final Config config;

    private final Map<Long, BlockingQueue<CardCommand>> queues = new ConcurrentHashMap<>();
    private final Map<String, CardCommand> inFlight = new ConcurrentHashMap<>();
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();
    private final Map<Long, String> activeSessionByBridge = new ConcurrentHashMap<>();

    @Inject
    public RemoteCardService(Config config) {
        this.config = config;
    }

    // -----------------------------------------------------------------------
    // Session lifecycle, called by the download worker
    // -----------------------------------------------------------------------

    /**
     * Takes exclusive use of a bridge's company card.
     *
     * @return an opaque session token
     * @throws CardUnavailableException when another download already holds the card
     */
    public String openSession(long bridgeId, long downloadJobId, long ttlSeconds)
            throws CardUnavailableException {

        String token = UUID.randomUUID().toString();
        Date expiresAt = new Date(System.currentTimeMillis() + ttlSeconds * 1000L);

        String existing = activeSessionByBridge.putIfAbsent(bridgeId, token);
        if (existing != null) {
            Session current = sessions.get(existing);
            if (current != null && current.expiresAt.after(new Date())) {
                throw new CardUnavailableException(String.format(
                        "Company card on bridge %d is in use by download job %d",
                        bridgeId, current.downloadJobId));
            }
            // The previous holder expired without closing; reclaim the card.
            LOGGER.warn("Reclaiming expired card session {} on bridge {}", existing, bridgeId);
            closeSession(existing);
            if (activeSessionByBridge.putIfAbsent(bridgeId, token) != null) {
                throw new CardUnavailableException(
                        "Company card on bridge " + bridgeId + " is in use");
            }
        }

        sessions.put(token, new Session(bridgeId, downloadJobId, expiresAt));
        LOGGER.info("Opened card session on bridge {} for download job {}", bridgeId, downloadJobId);
        return token;
    }

    /** Extends a session that is taking longer than expected. */
    public void extendSession(String token, long ttlSeconds) {
        Session session = sessions.get(token);
        if (session != null) {
            session.expiresAt = new Date(System.currentTimeMillis() + ttlSeconds * 1000L);
        }
    }

    /** Releases the card and fails any command still waiting on this session. */
    public void closeSession(String token) {
        Session session = sessions.remove(token);
        if (session == null) {
            return;
        }
        activeSessionByBridge.remove(session.bridgeId, token);

        BlockingQueue<CardCommand> queue = queues.get(session.bridgeId);
        if (queue != null) {
            queue.removeIf(command -> {
                if (token.equals(command.getSessionToken())) {
                    command.getFuture().complete(
                            CardResponse.failure("TACHO_CARD_SESSION_CLOSED", "Card session closed"));
                    return true;
                }
                return false;
            });
        }
        inFlight.values().removeIf(command -> {
            if (token.equals(command.getSessionToken())) {
                command.getFuture().complete(
                        CardResponse.failure("TACHO_CARD_SESSION_CLOSED", "Card session closed"));
                return true;
            }
            return false;
        });
        LOGGER.info("Closed card session on bridge {} for download job {}",
                session.bridgeId, session.downloadJobId);
    }

    public boolean isSessionOpen(String token) {
        Session session = sessions.get(token);
        return session != null && session.expiresAt.after(new Date());
    }

    /** The download job that currently holds a bridge's card, or null when it is free. */
    public Long getHoldingJob(long bridgeId) {
        String token = activeSessionByBridge.get(bridgeId);
        Session session = token != null ? sessions.get(token) : null;
        return session != null ? session.downloadJobId : null;
    }

    // -----------------------------------------------------------------------
    // Command round trip
    // -----------------------------------------------------------------------

    /**
     * Sends one command to the card and waits for the bridge to return the answer.
     *
     * @throws CardUnavailableException when the session is gone or the bridge does not answer
     */
    public CardResponse submit(String token, String type, byte[] request)
            throws CardUnavailableException {

        Session session = sessions.get(token);
        if (session == null) {
            throw new CardUnavailableException("Card session is not open");
        }
        if (!session.expiresAt.after(new Date())) {
            throw new CardUnavailableException("Card session has expired");
        }

        CardCommand command = new CardCommand(UUID.randomUUID().toString(), token, type, request);
        queues.computeIfAbsent(session.bridgeId, id -> new LinkedBlockingQueue<>()).add(command);

        long timeoutSeconds = config.getInteger(Keys.TACHO_CARD_APDU_TIMEOUT);
        try {
            return command.getFuture().get(timeoutSeconds, TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            queues.getOrDefault(session.bridgeId, new LinkedBlockingQueue<>()).remove(command);
            inFlight.remove(command.getId());
            throw new CardUnavailableException(String.format(
                    "Bridge %d did not answer a card command within %d s", session.bridgeId, timeoutSeconds));
        } catch (ExecutionException e) {
            throw new CardUnavailableException("Card command failed: " + e.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new CardUnavailableException("Interrupted while waiting for the company card");
        }
    }

    // -----------------------------------------------------------------------
    // Bridge side
    // -----------------------------------------------------------------------

    /**
     * Long-polls for the next command a bridge should execute.
     *
     * @return the command, or null when the wait elapsed with nothing to do
     */
    public CardCommand poll(long bridgeId, long timeoutSeconds) {
        BlockingQueue<CardCommand> queue =
                queues.computeIfAbsent(bridgeId, id -> new LinkedBlockingQueue<>());
        try {
            CardCommand command = queue.poll(Math.max(0, timeoutSeconds), TimeUnit.SECONDS);
            if (command != null) {
                inFlight.put(command.getId(), command);
            }
            return command;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        }
    }

    /**
     * Delivers a bridge's answer to the worker that is waiting for it.
     *
     * @return false when the command is unknown, already answered, or belongs to another bridge
     */
    public boolean complete(long bridgeId, String commandId, CardResponse response) {
        CardCommand command = inFlight.remove(commandId);
        if (command == null) {
            LOGGER.warn("Bridge {} answered unknown or expired card command {}", bridgeId, commandId);
            return false;
        }
        Session session = sessions.get(command.getSessionToken());
        if (session == null || session.bridgeId != bridgeId) {
            LOGGER.warn("Bridge {} answered card command {} that belongs to another session",
                    bridgeId, commandId);
            return false;
        }
        return command.getFuture().complete(response);
    }

    /** Drops any queued work for a bridge that has gone away. */
    public void purge(long bridgeId) {
        BlockingQueue<CardCommand> queue = queues.remove(bridgeId);
        if (queue != null) {
            queue.forEach(command -> command.getFuture().complete(
                    CardResponse.failure("TACHO_BRIDGE_UNAVAILABLE", "Bridge disconnected")));
            queue.clear();
        }
        String token = activeSessionByBridge.get(bridgeId);
        if (token != null) {
            closeSession(token);
        }
    }
}
