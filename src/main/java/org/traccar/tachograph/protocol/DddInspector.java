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

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;

/**
 * Reads descriptive fields out of an assembled DDD file and checks that it is structurally sound.
 *
 * <p>Field offsets come from the Annex 1B data dictionary. Only generation 1 overview and
 * technical-data blocks have fixed offsets that can be trusted without a full ASN.1 parse;
 * generation 2 blocks carry variable-length certificates, so those files are validated
 * structurally and reported with a warning rather than parsed for vehicle identity.
 *
 * <p>This class deliberately does not verify the digital signatures in the file. Signature
 * verification requires the European Root Certificate chain and is the analysis bureau's
 * responsibility; the server's job is to deliver the bytes unaltered, which the stored
 * SHA-256 digest attests.
 */
public final class DddInspector {

    /** Annex 1B generation 1 certificate length, used to locate fields in the overview block. */
    private static final int CERTIFICATE_LENGTH = 194;

    private static final int VIN_LENGTH = 17;
    private static final int REGISTRATION_NUMBER_LENGTH = 13;

    // VuIdentification field sizes at the start of the generation 1 technical data block.
    private static final int MANUFACTURER_NAME_LENGTH = 36;
    private static final int MANUFACTURER_ADDRESS_LENGTH = 36;
    private static final int PART_NUMBER_LENGTH = 16;
    private static final int SERIAL_NUMBER_LENGTH = 8;

    private DddInspector() {
    }

    /**
     * Validates the overall shape of a DDD file.
     *
     * @throws VuProtocolException when the file cannot be a DDD file at all
     */
    public static void validateStructure(byte[] data) throws VuProtocolException {
        if (data == null || data.length < 4) {
            throw new VuProtocolException("DDD file is empty or truncated");
        }
        int serviceId = data[0] & 0xFF;
        if (serviceId != VuMessage.SID_TRANSFER_DATA + VuMessage.POSITIVE_RESPONSE_OFFSET) {
            throw new VuProtocolException(String.format(
                    "DDD file does not start with a TransferData response (found 0x%02X)", serviceId));
        }
        TrepType first = TrepType.fromCode(data[1] & 0xFF);
        if (first == null) {
            throw new VuProtocolException(String.format(
                    "DDD file starts with unknown TREP 0x%02X", data[1] & 0xFF));
        }
    }

    /**
     * Extracts metadata using the block boundaries recorded while the file was assembled.
     * This is the reliable path and is what the download pipeline uses.
     */
    public static DddMetadata inspect(byte[] data, List<DddBlock> blocks) {
        DddMetadata metadata = new DddMetadata();
        if (data == null || data.length == 0 || blocks == null || blocks.isEmpty()) {
            metadata.addWarning("No data blocks were captured");
            return metadata;
        }

        for (DddBlock block : blocks) {
            metadata.getBlocks().add(block.getTrep().getLabel());
            metadata.setGeneration(Math.max(metadata.getGeneration(), block.getTrep().getGeneration()));
        }

        for (DddBlock block : blocks) {
            switch (block.getTrep()) {
                case OVERVIEW -> readOverviewGen1(data, block, metadata);
                case TECHNICAL_DATA -> readTechnicalDataGen1(data, block, metadata);
                default -> { }
            }
        }

        if (metadata.getGeneration() > 1 && metadata.getVehicleIdentificationNumber() == null) {
            metadata.addWarning(
                    "Generation " + metadata.getGeneration() + " overview block uses variable-length "
                            + "certificates; vehicle identity was not extracted from the file");
        }
        return metadata;
    }

    /**
     * Best-effort inspection of a file whose block boundaries are unknown, for example one that
     * an operator uploaded. Only the leading block is located, because scanning for further
     * {@code 0x76 TREP} markers would false-positive on payload bytes.
     */
    public static DddMetadata inspect(byte[] data) {
        DddMetadata metadata = new DddMetadata();
        if (data == null || data.length < 2) {
            metadata.addWarning("File is empty or truncated");
            return metadata;
        }
        TrepType first = TrepType.fromCode(data[1] & 0xFF);
        if (first == null) {
            metadata.addWarning("File does not begin with a recognised TREP block");
            return metadata;
        }
        metadata.setGeneration(first.getGeneration());
        metadata.getBlocks().add(first.getLabel());
        if (first == TrepType.OVERVIEW) {
            readOverviewGen1(data, new DddBlock(first, null, 0, data.length), metadata);
        }
        metadata.addWarning("Block boundaries were not recorded; only the first block was inspected");
        return metadata;
    }

    // -----------------------------------------------------------------------
    // Generation 1 block layouts
    // -----------------------------------------------------------------------

    /**
     * Generation 1 overview block, Annex 1B Appendix 7 section 2.2.6.1. Layout after the
     * two-byte {@code 76 01} prefix: member state certificate, vehicle unit certificate,
     * vehicle identification number, vehicle registration identification, current date and
     * time, then the downloadable period.
     */
    private static void readOverviewGen1(byte[] data, DddBlock block, DddMetadata metadata) {
        int base = block.getOffset() + 2;
        int vinOffset = base + CERTIFICATE_LENGTH * 2;
        int registrationOffset = vinOffset + VIN_LENGTH;
        int currentTimeOffset = registrationOffset + 1 + 1 + REGISTRATION_NUMBER_LENGTH;
        int periodOffset = currentTimeOffset + 4;

        if (periodOffset + 8 > block.getOffset() + block.getLength() || periodOffset + 8 > data.length) {
            metadata.addWarning("Overview block is shorter than the Annex 1B layout requires");
            return;
        }

        metadata.setVehicleIdentificationNumber(readString(data, vinOffset, VIN_LENGTH));
        metadata.setVehicleRegistrationNation(data[registrationOffset] & 0xFF);
        // Skip the code page byte that precedes the registration characters.
        metadata.setVehicleRegistrationNumber(
                readString(data, registrationOffset + 2, REGISTRATION_NUMBER_LENGTH));
        metadata.setCurrentDateTime(readTimeReal(data, currentTimeOffset));
        metadata.setDownloadablePeriodFrom(readTimeReal(data, periodOffset));
        metadata.setDownloadablePeriodTo(readTimeReal(data, periodOffset + 4));
    }

    /**
     * Generation 1 technical data block, which opens with {@code VuIdentification}:
     * manufacturer name, manufacturer address, part number, then the extended serial number.
     */
    private static void readTechnicalDataGen1(byte[] data, DddBlock block, DddMetadata metadata) {
        int base = block.getOffset() + 2;
        int serialOffset = base + MANUFACTURER_NAME_LENGTH + MANUFACTURER_ADDRESS_LENGTH + PART_NUMBER_LENGTH;

        if (serialOffset + SERIAL_NUMBER_LENGTH > block.getOffset() + block.getLength()
                || serialOffset + SERIAL_NUMBER_LENGTH > data.length) {
            metadata.addWarning("Technical data block is shorter than the Annex 1B layout requires");
            return;
        }

        metadata.setVehicleUnitManufacturer(readString(data, base, MANUFACTURER_NAME_LENGTH));

        // ExtendedSerialNumber: a four-byte serial, a BCD month and year, a type byte and a
        // manufacturer code. Operators identify a unit by the serial, so that is what is stored.
        long serial = ((long) (data[serialOffset] & 0xFF) << 24)
                | ((long) (data[serialOffset + 1] & 0xFF) << 16)
                | ((long) (data[serialOffset + 2] & 0xFF) << 8)
                | (data[serialOffset + 3] & 0xFF);
        metadata.setVehicleUnitSerialNumber(Long.toString(serial));
    }

    // -----------------------------------------------------------------------
    // Primitive readers
    // -----------------------------------------------------------------------

    /**
     * Reads a fixed-length regulation string. Unused positions are padded with spaces, nulls or
     * 0xFF depending on the manufacturer, so all three are stripped.
     */
    private static String readString(byte[] data, int offset, int length) {
        if (offset < 0 || offset + length > data.length) {
            return null;
        }
        int end = offset + length;
        while (end > offset) {
            int b = data[end - 1] & 0xFF;
            if (b == 0x00 || b == 0x20 || b == 0xFF) {
                end--;
            } else {
                break;
            }
        }
        int start = offset;
        while (start < end && (data[start] & 0xFF) == 0x20) {
            start++;
        }
        if (start >= end) {
            return null;
        }
        String value = new String(data, start, end - start, StandardCharsets.ISO_8859_1).trim();
        return value.isEmpty() ? null : value;
    }

    /**
     * Reads a {@code TimeReal}: seconds since 1970-01-01 00:00:00 UTC as a four-byte unsigned
     * big-endian integer. Zero means "not set" in the regulation and maps to null here.
     */
    private static Date readTimeReal(byte[] data, int offset) {
        if (offset < 0 || offset + 4 > data.length) {
            return null;
        }
        long seconds = ((long) (data[offset] & 0xFF) << 24)
                | ((long) (data[offset + 1] & 0xFF) << 16)
                | ((long) (data[offset + 2] & 0xFF) << 8)
                | (data[offset + 3] & 0xFF);
        return seconds == 0 ? null : new Date(seconds * 1000L);
    }
}
