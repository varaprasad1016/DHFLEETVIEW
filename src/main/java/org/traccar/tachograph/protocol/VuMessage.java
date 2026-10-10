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
package org.traccar.tachograph.protocol;

import java.util.Arrays;

/**
 * One message of the vehicle-unit data download protocol (KWP2000 / ISO 14230-2 framing as
 * profiled by Annex 1B Appendix 7 section 2.2).
 *
 * <p>Wire layout:
 * <pre>
 *   Fmt | Tgt | Src | Len | Data field (Len bytes) | Checksum
 * </pre>
 * {@code Fmt} is {@code 0x80} (headers with an explicit length byte), {@code Tgt}/{@code Src} are
 * {@link #ADDRESS_VU} and {@link #ADDRESS_TESTER}, and {@code Checksum} is the arithmetic sum of
 * every preceding byte modulo 256.
 */
public final class VuMessage {

    /** Address of the vehicle unit (the tachograph). */
    public static final int ADDRESS_VU = 0xEE;
    /** Address of the downloading device (this server, acting as the tester). */
    public static final int ADDRESS_TESTER = 0xF0;

    /** Format byte: header carries an explicit length byte. */
    public static final int FORMAT = 0x80;

    // Service identifiers, Annex 1B Appendix 7 section 2.2.2.
    public static final int SID_START_COMMUNICATION = 0x81;
    public static final int SID_STOP_COMMUNICATION = 0x82;
    public static final int SID_ACCESS_TIMING = 0x83;
    public static final int SID_START_DIAGNOSTIC_SESSION = 0x10;
    public static final int SID_REQUEST_UPLOAD = 0x35;
    public static final int SID_TRANSFER_DATA = 0x36;
    public static final int SID_REQUEST_TRANSFER_EXIT = 0x37;
    public static final int SID_NEGATIVE_RESPONSE = 0x7F;

    /** A positive response identifier is the request identifier plus 0x40. */
    public static final int POSITIVE_RESPONSE_OFFSET = 0x40;

    /** Negative response code meaning "request received, response pending" — keep waiting. */
    public static final int NRC_RESPONSE_PENDING = 0x78;
    /** Negative response code meaning the vehicle unit is busy and the request must be repeated. */
    public static final int NRC_BUSY_REPEAT_REQUEST = 0x21;

    /** Maximum size of the data field, bounded by the single-byte length field. */
    public static final int MAX_DATA_LENGTH = 255;

    /** Smallest possible message: format, target, source, length, one data byte, checksum. */
    public static final int MIN_MESSAGE_LENGTH = 6;

    private final int target;
    private final int source;
    private final byte[] data;

    public VuMessage(int target, int source, byte[] data) {
        if (data == null || data.length == 0) {
            throw new IllegalArgumentException("Vehicle unit message data field must not be empty");
        }
        if (data.length > MAX_DATA_LENGTH) {
            throw new IllegalArgumentException(
                    "Vehicle unit message data field exceeds " + MAX_DATA_LENGTH + " bytes: " + data.length);
        }
        this.target = target;
        this.source = source;
        this.data = data;
    }

    /** Builds a request addressed from the tester to the vehicle unit. */
    public static VuMessage request(byte... data) {
        return new VuMessage(ADDRESS_VU, ADDRESS_TESTER, data);
    }

    public int getTarget() {
        return target;
    }

    public int getSource() {
        return source;
    }

    public byte[] getData() {
        return data;
    }

    /** The service identifier, which is always the first byte of the data field. */
    public int getServiceId() {
        return data[0] & 0xFF;
    }

    /** The data field with the service identifier removed. */
    public byte[] getPayload() {
        return Arrays.copyOfRange(data, 1, data.length);
    }

    public boolean isNegativeResponse() {
        return getServiceId() == SID_NEGATIVE_RESPONSE;
    }

    /**
     * For a negative response, the service identifier the response refers to,
     * or -1 when this message is not a negative response.
     */
    public int getNegativeRequestId() {
        return isNegativeResponse() && data.length > 1 ? data[1] & 0xFF : -1;
    }

    /**
     * For a negative response, the response code (for example {@link #NRC_RESPONSE_PENDING}),
     * or -1 when this message is not a negative response.
     */
    public int getNegativeResponseCode() {
        return isNegativeResponse() && data.length > 2 ? data[2] & 0xFF : -1;
    }

    /** Whether this message is the positive response to the given request service identifier. */
    public boolean isPositiveResponseTo(int requestServiceId) {
        return getServiceId() == (requestServiceId + POSITIVE_RESPONSE_OFFSET);
    }

    /** Serialises the message including header and trailing checksum. */
    public byte[] encode() {
        byte[] frame = new byte[4 + data.length + 1];
        frame[0] = (byte) FORMAT;
        frame[1] = (byte) target;
        frame[2] = (byte) source;
        frame[3] = (byte) data.length;
        System.arraycopy(data, 0, frame, 4, data.length);
        frame[frame.length - 1] = (byte) checksum(frame, 0, frame.length - 1);
        return frame;
    }

    /**
     * Total on-the-wire length of the message starting at {@code offset}, or -1 when
     * {@code buffer} does not yet hold a complete message.
     *
     * @throws VuProtocolException when the header is structurally invalid
     */
    public static int frameLength(byte[] buffer, int offset, int available) throws VuProtocolException {
        if (available < 4) {
            return -1;
        }
        int format = buffer[offset] & 0xFF;
        if (format != FORMAT) {
            throw new VuProtocolException(
                    String.format("Unexpected vehicle unit format byte 0x%02X (expected 0x%02X)", format, FORMAT));
        }
        int length = buffer[offset + 3] & 0xFF;
        if (length == 0) {
            throw new VuProtocolException("Vehicle unit message declares a zero-length data field");
        }
        int total = 4 + length + 1;
        return available < total ? -1 : total;
    }

    /**
     * Parses exactly one message from {@code buffer} starting at {@code offset}.
     *
     * @throws VuProtocolException when the checksum does not match or the frame is truncated
     */
    public static VuMessage decode(byte[] buffer, int offset, int available) throws VuProtocolException {
        int total = frameLength(buffer, offset, available);
        if (total < 0) {
            throw new VuProtocolException("Incomplete vehicle unit message");
        }
        int length = buffer[offset + 3] & 0xFF;
        int expected = checksum(buffer, offset, total - 1);
        int actual = buffer[offset + total - 1] & 0xFF;
        if (expected != actual) {
            throw new VuProtocolException(String.format(
                    "Vehicle unit checksum mismatch: computed 0x%02X, received 0x%02X", expected, actual));
        }
        byte[] data = Arrays.copyOfRange(buffer, offset + 4, offset + 4 + length);
        return new VuMessage(buffer[offset + 1] & 0xFF, buffer[offset + 2] & 0xFF, data);
    }

    private static int checksum(byte[] buffer, int offset, int length) {
        int sum = 0;
        for (int i = offset; i < offset + length; i++) {
            sum += buffer[i] & 0xFF;
        }
        return sum & 0xFF;
    }

    @Override
    public String toString() {
        return String.format("VuMessage[tgt=%02X src=%02X sid=%02X len=%d]",
                target, source, getServiceId(), data.length);
    }
}
