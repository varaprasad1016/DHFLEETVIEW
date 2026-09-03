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

import java.util.Date;
import java.util.concurrent.CompletableFuture;

/**
 * One command awaiting execution against a company card held in a remote reader.
 *
 * <p>A command is created by the download worker, handed to a bridge when it polls, and
 * completed when the bridge posts the card's answer back. The {@link CompletableFuture} is how
 * the worker thread waits for that round trip.
 *
 * <p>The command and response bytes are application protocol data units exchanged verbatim with
 * the card. The server does not interpret them and must never log them: an authentication
 * exchange carries challenge and cryptogram material.
 */
public class CardCommand {

    /** Transmit an APDU to the card and return its response. */
    public static final String TYPE_TRANSMIT = "TRANSMIT";
    /** Reconnect to the card, returning the answer to reset. */
    public static final String TYPE_RESET = "RESET";
    /** Read the card's identity files so the operator can see which card is fitted. */
    public static final String TYPE_IDENTIFY = "IDENTIFY";

    private final String id;
    private final String sessionToken;
    private final String type;
    private final byte[] request;
    private final Date createdAt = new Date();
    private final CompletableFuture<CardResponse> future = new CompletableFuture<>();

    public CardCommand(String id, String sessionToken, String type, byte[] request) {
        this.id = id;
        this.sessionToken = sessionToken;
        this.type = type;
        this.request = request;
    }

    public String getId() {
        return id;
    }

    public String getSessionToken() {
        return sessionToken;
    }

    public String getType() {
        return type;
    }

    public byte[] getRequest() {
        return request;
    }

    public Date getCreatedAt() {
        return createdAt;
    }

    public CompletableFuture<CardResponse> getFuture() {
        return future;
    }
}
