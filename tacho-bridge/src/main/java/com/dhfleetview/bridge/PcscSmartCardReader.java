package com.dhfleetview.bridge;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.smartcardio.Card;
import javax.smartcardio.CardChannel;
import javax.smartcardio.CardException;
import javax.smartcardio.CardTerminal;
import javax.smartcardio.TerminalFactory;

/**
 * PC/SC implementation using {@code javax.smartcardio}. Detects compatible
 * readers via the operating system's PC/SC subsystem.
 */
public class PcscSmartCardReader implements SmartCardReader {

    private static final Logger LOGGER = LoggerFactory.getLogger(PcscSmartCardReader.class);

    private CardTerminal terminal;
    private Card card;
    private CardChannel channel;

    @Override
    public void connect() throws Exception {
        TerminalFactory factory = TerminalFactory.getDefault();
        if (factory.terminals().list().isEmpty()) {
            throw new CardException("No PC/SC readers found");
        }
        terminal = factory.terminals().list().get(0);
        LOGGER.info("Using reader: {}", terminal.getName());
    }

    @Override
    public void disconnect() throws Exception {
        if (card != null) {
            try {
                card.disconnect(false);
            } catch (CardException ignored) {
            }
            card = null;
            channel = null;
        }
    }

    @Override
    public ReaderStatus getReaderStatus() {
        try {
            TerminalFactory factory = TerminalFactory.getDefault();
            if (factory.terminals().list().isEmpty()) {
                return ReaderStatus.NO_READER;
            }
            return ReaderStatus.READER_CONNECTED;
        } catch (CardException e) {
            return ReaderStatus.READER_ERROR;
        }
    }

    @Override
    public CardStatus getCardStatus() {
        if (terminal == null) {
            return CardStatus.NO_CARD;
        }
        try {
            if (!terminal.isCardPresent()) {
                return CardStatus.NO_CARD;
            }
            if (card == null || channel == null) {
                return CardStatus.CARD_INSERTED;
            }
            return CardStatus.CARD_READY;
        } catch (CardException e) {
            return CardStatus.CARD_ERROR;
        }
    }

    @Override
    public boolean isCardPresent() {
        if (terminal == null) {
            return false;
        }
        try {
            return terminal.isCardPresent();
        } catch (CardException e) {
            return false;
        }
    }

    @Override
    public CardInfo getCardInfo() {
        CardInfo info = new CardInfo();
        info.status = getCardStatus().name();
        if (terminal != null) {
            try {
                info.cardType = "COMPANY_CARD";
                // Real card identification would use SELECT + GET DATA APDUs per the
                // tachograph card specification. Not implemented until the spec is
                // available — see docs/tachograph/TACHO-BRIDGE.md.
            } catch (Exception e) {
                LOGGER.warn("Failed to read card info", e);
            }
        }
        return info;
    }

    @Override
    public byte[] transmit(byte[] command) throws Exception {
        if (channel == null) {
            if (terminal == null || !terminal.isCardPresent()) {
                throw new CardException("No card present");
            }
            card = terminal.connect("*");
            channel = card.getBasicChannel();
        }
        return channel.transmit(new javax.smartcardio.CommandAPDU(command)).getBytes();
    }
}
