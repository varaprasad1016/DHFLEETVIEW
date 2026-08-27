package com.dhfleetview.bridge;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Mock reader for simulator/testing ONLY.
 * TEST ONLY - NOT FOR PRODUCTION.
 */
public class MockSmartCardReader implements SmartCardReader {

    private static final Logger LOGGER = LoggerFactory.getLogger(MockSmartCardReader.class);

    private boolean cardPresent = true;

    public void setCardPresent(boolean present) {
        this.cardPresent = present;
        LOGGER.info("Mock card present={}", present);
    }

    @Override
    public ReaderStatus getReaderStatus() {
        return ReaderStatus.READER_CONNECTED;
    }

    @Override
    public CardStatus getCardStatus() {
        return cardPresent ? CardStatus.CARD_READY : CardStatus.NO_CARD;
    }

    @Override
    public boolean isCardPresent() {
        return cardPresent;
    }

    @Override
    public CardInfo getCardInfo() {
        CardInfo info = new CardInfo();
        info.cardIdentifier = "MOCK_CARD_001";
        info.cardType = "COMPANY_CARD";
        info.status = "VALID";
        return info;
    }

    @Override
    public byte[] transmit(byte[] command) {
        // Mock: echo the command with a success status word 0x9000.
        byte[] response = new byte[2];
        response[0] = (byte) 0x90;
        response[1] = 0x00;
        return response;
    }

    @Override
    public void connect() {
        LOGGER.info("Mock reader connected");
    }

    @Override
    public void disconnect() {
        LOGGER.info("Mock reader disconnected");
    }
}
