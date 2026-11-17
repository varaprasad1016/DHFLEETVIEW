package org.traccar.tachograph.protocol;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class VuMessageTest {

    @Test
    public void testEncodeStartCommunication() {
        // 80 EE F0 01 81 + checksum, per Annex 1B Appendix 7.
        byte[] encoded = VuMessage.request((byte) VuMessage.SID_START_COMMUNICATION).encode();

        assertArrayEquals(
                new byte[] {(byte) 0x80, (byte) 0xEE, (byte) 0xF0, 0x01, (byte) 0x81, (byte) 0xE0},
                encoded);
    }

    @Test
    public void testChecksumIsSumOfPrecedingBytes() {
        byte[] encoded = VuMessage.request((byte) 0x36, (byte) 0x01).encode();

        int sum = 0;
        for (int i = 0; i < encoded.length - 1; i++) {
            sum += encoded[i] & 0xFF;
        }
        assertEquals(sum & 0xFF, encoded[encoded.length - 1] & 0xFF);
    }

    @Test
    public void testDecodeRoundTrip() throws Exception {
        VuMessage original = VuMessage.request((byte) 0x36, (byte) 0x02, (byte) 0xAA, (byte) 0xBB);
        byte[] encoded = original.encode();

        VuMessage decoded = VuMessage.decode(encoded, 0, encoded.length);

        assertEquals(VuMessage.ADDRESS_VU, decoded.getTarget());
        assertEquals(VuMessage.ADDRESS_TESTER, decoded.getSource());
        assertEquals(0x36, decoded.getServiceId());
        assertArrayEquals(new byte[] {0x02, (byte) 0xAA, (byte) 0xBB}, decoded.getPayload());
    }

    @Test
    public void testFrameLengthReportsIncompleteFrame() throws Exception {
        byte[] encoded = VuMessage.request((byte) 0x36, (byte) 0x01).encode();

        assertEquals(-1, VuMessage.frameLength(encoded, 0, 3));
        assertEquals(-1, VuMessage.frameLength(encoded, 0, encoded.length - 1));
        assertEquals(encoded.length, VuMessage.frameLength(encoded, 0, encoded.length));
    }

    @Test
    public void testCorruptChecksumIsRejected() {
        byte[] encoded = VuMessage.request((byte) 0x36, (byte) 0x01).encode();
        encoded[encoded.length - 1] ^= 0xFF;

        assertThrows(VuProtocolException.class,
                () -> VuMessage.decode(encoded, 0, encoded.length));
    }

    @Test
    public void testUnexpectedFormatByteIsRejected() {
        byte[] encoded = VuMessage.request((byte) 0x36, (byte) 0x01).encode();
        encoded[0] = 0x00;

        assertThrows(VuProtocolException.class,
                () -> VuMessage.frameLength(encoded, 0, encoded.length));
    }

    @Test
    public void testNegativeResponseFields() throws Exception {
        VuMessage message = new VuMessage(
                VuMessage.ADDRESS_TESTER, VuMessage.ADDRESS_VU,
                new byte[] {(byte) VuMessage.SID_NEGATIVE_RESPONSE, 0x36, (byte) 0x78});
        byte[] encoded = message.encode();

        VuMessage decoded = VuMessage.decode(encoded, 0, encoded.length);

        assertTrue(decoded.isNegativeResponse());
        assertEquals(0x36, decoded.getNegativeRequestId());
        assertEquals(VuMessage.NRC_RESPONSE_PENDING, decoded.getNegativeResponseCode());
        assertFalse(decoded.isPositiveResponseTo(0x36));
    }

    @Test
    public void testPositiveResponseIdentification() {
        VuMessage response = new VuMessage(
                VuMessage.ADDRESS_TESTER, VuMessage.ADDRESS_VU, new byte[] {0x76, 0x01});

        assertTrue(response.isPositiveResponseTo(VuMessage.SID_TRANSFER_DATA));
        assertFalse(response.isPositiveResponseTo(VuMessage.SID_REQUEST_UPLOAD));
    }

    @Test
    public void testOversizedDataFieldIsRejected() {
        byte[] tooLong = new byte[VuMessage.MAX_DATA_LENGTH + 1];

        assertThrows(IllegalArgumentException.class, () -> VuMessage.request(tooLong));
    }
}
