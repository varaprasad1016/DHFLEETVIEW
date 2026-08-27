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
