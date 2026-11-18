/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
package com.dhfleetview.bridge;

/**
 * Abstraction for a PC/SC smart-card reader.
 */
public interface SmartCardReader {

    enum ReaderStatus {
        NO_READER,
        READER_CONNECTED,
        READER_ERROR
    }

    enum CardStatus {
        NO_CARD,
        CARD_INSERTED,
        CARD_READY,
        CARD_ERROR,
        CARD_REMOVED
    }

    ReaderStatus getReaderStatus();

    CardStatus getCardStatus();

    boolean isCardPresent();

    CardInfo getCardInfo();

    /**
     * Transmits an APDU to the card. Returns the response bytes (data + SW).
     * The implementation MUST NOT log the raw payload indiscriminately.
     */
    byte[] transmit(byte[] command) throws Exception;

    void connect() throws Exception;

    void disconnect() throws Exception;
}
