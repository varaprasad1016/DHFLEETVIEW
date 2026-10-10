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

import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * Reads the identity of a company card through a bridge, and decodes the
 * {@code EF_Identification} file layout defined by the Annex 1B data dictionary.
 *
 * <p>Layout for a company card, in order: issuing member state, card number, issuing authority
 * name, issue date, validity start, expiry date, then the holder block with the company name,
 * company address and preferred language.
 */
public final class CardIdentityReader {

    private static final int CARD_NUMBER_LENGTH = 16;
    private static final int NAME_LENGTH = 36;
    private static final int IDENTIFICATION_LENGTH = 139;

    private static final int OFFSET_CARD_NUMBER = 1;
    private static final int OFFSET_AUTHORITY = OFFSET_CARD_NUMBER + CARD_NUMBER_LENGTH;
    private static final int OFFSET_ISSUE_DATE = OFFSET_AUTHORITY + NAME_LENGTH;
    private static final int OFFSET_VALIDITY_BEGIN = OFFSET_ISSUE_DATE + 4;
    private static final int OFFSET_EXPIRY_DATE = OFFSET_VALIDITY_BEGIN + 4;
    private static final int OFFSET_COMPANY_NAME = OFFSET_EXPIRY_DATE + 4;
    private static final int OFFSET_COMPANY_ADDRESS = OFFSET_COMPANY_NAME + NAME_LENGTH;

    private CardIdentityReader() {
    }

    /**
     * Selects the tachograph application and reads the identification file over the relay.
     *
     * @return the decoded identity
     * @throws CardUnavailableException when any step fails or the card refuses a command
     */
    public static CardIdentity read(RemoteCardService cardService, String sessionToken)
            throws CardUnavailableException {

        expectSuccess(cardService.submit(sessionToken, CardCommand.TYPE_TRANSMIT,
                CardApdu.selectApplication()), "select tachograph application");
        expectSuccess(cardService.submit(sessionToken, CardCommand.TYPE_TRANSMIT,
                CardApdu.selectFile(CardApdu.EF_IDENTIFICATION)), "select identification file");

        byte[] content = readFile(cardService, sessionToken, IDENTIFICATION_LENGTH);
        return decode(content);
    }

    /** Reads a selected file in chunks the card is willing to return in one response. */
    private static byte[] readFile(RemoteCardService cardService, String sessionToken, int length)
            throws CardUnavailableException {

        byte[] content = new byte[length];
        int offset = 0;
        while (offset < length) {
            int chunk = Math.min(255, length - offset);
            CardResponse response = cardService.submit(
                    sessionToken, CardCommand.TYPE_TRANSMIT, CardApdu.readBinary(offset, chunk));
            if (!response.isSuccess()) {
                throw new CardUnavailableException(
                        "Reading the company card failed: " + response.getErrorMessage());
            }
            int statusWord = response.getStatusWord();
            if ((statusWord >> 8) == CardApdu.SW1_WRONG_LENGTH) {
                // The card is telling us the exact length it will return; ask again for that.
                chunk = statusWord & 0xFF;
                if (chunk == 0) {
                    break;
                }
                response = cardService.submit(
                        sessionToken, CardCommand.TYPE_TRANSMIT, CardApdu.readBinary(offset, chunk));
            }
            if (!CardApdu.isSuccess(response)) {
                throw new CardUnavailableException(String.format(
                        "Company card rejected a read at offset %d with status 0x%04X",
                        offset, response.getStatusWord()));
            }
            byte[] body = CardApdu.body(response);
            if (body.length == 0) {
                break;
            }
            int copy = Math.min(body.length, length - offset);
            System.arraycopy(body, 0, content, offset, copy);
            offset += copy;
        }
        return content;
    }

    /** Decodes the identification file content. Fields that are blank on the card stay null. */
    public static CardIdentity decode(byte[] content) {
        CardIdentity identity = new CardIdentity();
        if (content == null || content.length < OFFSET_COMPANY_NAME) {
            return identity;
        }
        identity.setIssuingMemberState(content[0] & 0xFF);
        identity.setCardNumber(readString(content, OFFSET_CARD_NUMBER, CARD_NUMBER_LENGTH));
        identity.setIssuingAuthority(readCodePagedString(content, OFFSET_AUTHORITY, NAME_LENGTH));
        identity.setIssueDate(readTimeReal(content, OFFSET_ISSUE_DATE));
        identity.setValidityBegin(readTimeReal(content, OFFSET_VALIDITY_BEGIN));
        identity.setExpiryDate(readTimeReal(content, OFFSET_EXPIRY_DATE));
        identity.setCompanyName(readCodePagedString(content, OFFSET_COMPANY_NAME, NAME_LENGTH));
        identity.setCompanyAddress(readCodePagedString(content, OFFSET_COMPANY_ADDRESS, NAME_LENGTH));
        return identity;
    }

    private static void expectSuccess(CardResponse response, String step)
            throws CardUnavailableException {
        if (!response.isSuccess()) {
            throw new CardUnavailableException(
                    "Company card could not " + step + ": " + response.getErrorMessage());
        }
        if (response.getStatusWord() != CardApdu.SW_SUCCESS) {
            throw new CardUnavailableException(String.format(
                    "Company card refused to %s, status 0x%04X", step, response.getStatusWord()));
        }
    }

    /** Reads a plain fixed-length string, trimming the regulation's padding bytes. */
    private static String readString(byte[] data, int offset, int length) {
        if (offset + length > data.length) {
            return null;
        }
        int end = offset + length;
        while (end > offset) {
            int value = data[end - 1] & 0xFF;
            if (value == 0x00 || value == 0x20 || value == 0xFF) {
                end--;
            } else {
                break;
            }
        }
        if (end <= offset) {
            return null;
        }
        String text = new String(data, offset, end - offset, StandardCharsets.ISO_8859_1).trim();
        return text.isEmpty() ? null : text;
    }

    /** Reads a string whose first byte is a code page selector rather than a character. */
    private static String readCodePagedString(byte[] data, int offset, int length) {
        return readString(data, offset + 1, length - 1);
    }

    private static Date readTimeReal(byte[] data, int offset) {
        if (offset + 4 > data.length) {
            return null;
        }
        long seconds = ((long) (data[offset] & 0xFF) << 24)
                | ((long) (data[offset + 1] & 0xFF) << 16)
                | ((long) (data[offset + 2] & 0xFF) << 8)
                | (data[offset + 3] & 0xFF);
        return seconds == 0 ? null : new Date(seconds * 1000L);
    }
}
