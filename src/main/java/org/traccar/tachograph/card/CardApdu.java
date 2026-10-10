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

/**
 * Application protocol data units for the tachograph card application, per Annex 1B Appendix 2.
 *
 * <p>These are only used to read the card's own identity files so an operator can see which
 * company card a bridge holds and be warned before it expires. The authentication exchange
 * between a vehicle unit and the card is relayed verbatim and is never constructed here — the
 * server has no key material and does not need any.
 */
public final class CardApdu {

    /** Application identifier of the tachograph application: the ASCII bytes of "TACHO". */
    private static final byte[] TACHOGRAPH_AID = {
        (byte) 0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F,
    };

    /** Elementary file holding card and card-holder identification. */
    public static final int EF_IDENTIFICATION = 0x0520;
    /** Elementary file holding the integrated circuit card serial number. */
    public static final int EF_ICC = 0x0002;

    /** Status word returned when a command succeeded. */
    public static final int SW_SUCCESS = 0x9000;
    /** Status word prefix meaning "success, but N bytes remain"; the low byte is the count. */
    public static final int SW1_MORE_DATA = 0x61;
    /** Status word prefix meaning the expected length was wrong; the low byte is the right one. */
    public static final int SW1_WRONG_LENGTH = 0x6C;

    private static final int MAX_READ_LENGTH = 0xFF;

    private CardApdu() {
    }

    /** Selects the tachograph application on the card. */
    public static byte[] selectApplication() {
        byte[] apdu = new byte[5 + TACHOGRAPH_AID.length];
        apdu[0] = 0x00;
        apdu[1] = (byte) 0xA4;
        apdu[2] = 0x04;
        apdu[3] = 0x0C;
        apdu[4] = (byte) TACHOGRAPH_AID.length;
        System.arraycopy(TACHOGRAPH_AID, 0, apdu, 5, TACHOGRAPH_AID.length);
        return apdu;
    }

    /** Selects an elementary file by its two-byte identifier. */
    public static byte[] selectFile(int fileId) {
        return new byte[] {
            0x00, (byte) 0xA4, 0x02, 0x0C, 0x02, (byte) (fileId >> 8), (byte) fileId,
        };
    }

    /**
     * Reads up to {@code length} bytes from the selected file starting at {@code offset}.
     * A length of 256 is encoded as zero, which the card reads as "the maximum".
     */
    public static byte[] readBinary(int offset, int length) {
        if (length < 1 || length > 256) {
            throw new IllegalArgumentException("Read length must be between 1 and 256: " + length);
        }
        return new byte[] {
            0x00, (byte) 0xB0, (byte) (offset >> 8), (byte) offset, (byte) (length & MAX_READ_LENGTH),
        };
    }

    /** Whether a response's status word indicates success. */
    public static boolean isSuccess(CardResponse response) {
        return response != null && response.isSuccess() && response.getStatusWord() == SW_SUCCESS;
    }

    /**
     * Strips the trailing two-byte status word from a card response.
     *
     * @return the data portion, which may be empty
     */
    public static byte[] body(CardResponse response) {
        byte[] data = response.getData();
        if (data == null || data.length <= 2) {
            return new byte[0];
        }
        byte[] body = new byte[data.length - 2];
        System.arraycopy(data, 0, body, 0, body.length);
        return body;
    }
}
