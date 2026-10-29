package org.traccar.tachograph.protocol;

import org.junit.jupiter.api.Test;
import org.traccar.tachograph.device.VirtualVehicleUnit;

import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Exercises the download protocol end to end against the vehicle-unit emulator.
 *
 * <p>These are the tests that matter most in this module. Every other layer can be checked by
 * reading it; whether the session driver, the framing and the file assembler agree with each
 * other over a multi-message transfer can only be checked by running one.
 */
public class VuDownloadSessionTest {

    /** The emulator answers instantly, so the block-idle gap can be very short. */
    private static final VuTimings FAST = VuTimings.of(2000, 50, 2000, 30000, 2);

    private VuDownloadSession openSession(VirtualVehicleUnit unit) throws Exception {
        VuDownloadSession session = new VuDownloadSession(unit, FAST, null);
        session.open();
        return session;
    }

    @Test
    public void testHandshakeReturnsKeyBytes() throws Exception {
        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(1, true);
             VuDownloadSession session = openSession(unit)) {

            assertArrayEqualsUnsigned(new int[] {0xEA, 0x8F}, session.getKeyBytes());
        }
    }

    /**
     * The overview block spans several messages, which is where the continuation rule bites.
     * Assembling the same block under both rules and comparing the lengths pins the behaviour
     * exactly: stripping the repeated header must remove two bytes per continuation message and
     * nothing else. Scanning the assembled bytes for {@code 76 01} would not do, because the
     * payload is certificate material that can contain those two bytes by chance.
     */
    @Test
    public void testContinuationMessagesAreStitchedWithoutDuplicateHeaders() throws Exception {
        byte[] stripped = downloadOverview(42, ContinuationMode.REPEAT_HEADER);
        byte[] raw = downloadOverview(42, ContinuationMode.RAW_CONTINUATION);

        assertEquals(0x76, stripped[0] & 0xFF);
        assertEquals(TrepType.OVERVIEW.getCode(), stripped[1] & 0xFF);

        assertTrue(stripped.length > VuMessage.MAX_DATA_LENGTH * 2,
                "expected a multi-message block, got " + stripped.length + " bytes");

        int payloadPerMessage = VuMessage.MAX_DATA_LENGTH - 2;
        int payloadLength = stripped.length - 2;
        int messageCount = (payloadLength + payloadPerMessage - 1) / payloadPerMessage;

        assertTrue(messageCount > 1, "the overview block should not fit in one message");
        assertEquals(2 * (messageCount - 1), raw.length - stripped.length,
                "exactly one repeated header per continuation message should be stripped");
    }

    @Test
    public void testGenerationTwoBlockIsRefusedByGenerationOneUnit() throws Exception {
        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(7, true);
             VuDownloadSession session = openSession(unit)) {

            VuProtocolException failure = assertThrows(VuProtocolException.class,
                    () -> session.downloadBlock(TrepType.OVERVIEW_G2, null));

            // A negative response code is what lets the client fall back to the next generation
            // rather than abandoning the download.
            assertTrue(failure.getNegativeResponseCode() >= 0);
        }
    }

    @Test
    public void testActivitiesAreDateRanged() throws Exception {
        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(9, true);
             VuDownloadSession session = openSession(unit)) {

            Date day = new Date(1_700_000_000_000L);
            byte[] block = session.downloadBlock(TrepType.ACTIVITIES, day);

            assertTrue(block.length > 0);
            assertEquals(TrepType.ACTIVITIES.getCode(), block[1] & 0xFF);
        }
    }

    @Test
    public void testActivitiesWithoutDayIsRejected() throws Exception {
        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(9, true);
             VuDownloadSession session = openSession(unit)) {

            assertThrows(VuProtocolException.class,
                    () -> session.downloadBlock(TrepType.ACTIVITIES, null));
        }
    }

    @Test
    public void testCardDownloadFailsWhenNoCardIsInserted() throws Exception {
        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(11, false);
             VuDownloadSession session = openSession(unit)) {

            assertThrows(VuProtocolException.class,
                    () -> session.downloadBlock(TrepType.CARD_DOWNLOAD, null));
        }
    }

    @Test
    public void testFullVehicleDownloadProducesAnInspectableFile() throws Exception {
        DddFileBuilder builder = new DddFileBuilder();

        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(12345, true);
             VuDownloadSession session = openSession(unit)) {

            Date day = new Date(1_700_000_000_000L);
            for (TrepType trep : TrepType.vehicleSequence(1, false)) {
                if (trep.isDateRanged()) {
                    builder.append(trep, day, session.downloadBlock(trep, day));
                } else {
                    builder.append(trep, null, session.downloadBlock(trep, null));
                }
            }
        }

        byte[] file = builder.toByteArray();
        DddInspector.validateStructure(file);

        DddMetadata metadata = DddInspector.inspect(file, builder.getBlocks());

        assertEquals(1, metadata.getGeneration());
        assertNotNull(metadata.getVehicleIdentificationNumber());
        assertNotNull(metadata.getVehicleRegistrationNumber());
        assertNotNull(metadata.getVehicleUnitSerialNumber());
        assertNotNull(metadata.getDownloadablePeriodFrom());
        assertNotNull(metadata.getDownloadablePeriodTo());

        assertTrue(metadata.getVehicleRegistrationNumber().startsWith("SIM"),
                "expected the emulator registration, got " + metadata.getVehicleRegistrationNumber());
        assertEquals(
                List.of("Overview", "Activities", "EventsAndFaults", "TechnicalData"),
                metadata.getBlocks());
    }

    @Test
    public void testEmulatorIsDeterministicForTheSameDevice() throws Exception {
        byte[] first = downloadOverview(999);
        byte[] second = downloadOverview(999);
        byte[] other = downloadOverview(1000);

        // Repeatable output is what makes delivery and de-duplication testable without hardware.
        assertEquals(first.length, second.length);
        assertTrue(java.util.Arrays.equals(first, second));
        assertTrue(!java.util.Arrays.equals(first, other));
    }

    @Test
    public void testStructureValidationRejectsNonDddContent() {
        assertThrows(VuProtocolException.class,
                () -> DddInspector.validateStructure("not a tachograph file".getBytes()));
        assertThrows(VuProtocolException.class,
                () -> DddInspector.validateStructure(new byte[] {0x76, 0x00, 0x00, 0x00}));
        assertThrows(VuProtocolException.class,
                () -> DddInspector.validateStructure(new byte[0]));
    }

    private byte[] downloadOverview(long deviceId) throws Exception {
        return downloadOverview(deviceId, ContinuationMode.REPEAT_HEADER);
    }

    private byte[] downloadOverview(long deviceId, ContinuationMode mode) throws Exception {
        try (VirtualVehicleUnit unit = new VirtualVehicleUnit(deviceId, true);
             VuDownloadSession session = new VuDownloadSession(unit, FAST, null, mode)) {
            session.open();
            return session.downloadBlock(TrepType.OVERVIEW, null);
        }
    }

    private void assertArrayEqualsUnsigned(int[] expected, byte[] actual) {
        assertEquals(expected.length, actual.length);
        for (int i = 0; i < expected.length; i++) {
            assertEquals(expected[i], actual[i] & 0xFF, "byte " + i);
        }
    }
}
