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
package org.traccar.tachograph.device;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.tachograph.protocol.TrepType;
import org.traccar.tachograph.protocol.VuChannel;
import org.traccar.tachograph.protocol.VuMessage;
import org.traccar.tachograph.protocol.VuProtocolException;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Random;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * An in-memory generation 1 vehicle unit that answers the real download protocol.
 *
 * <p>This is what {@code tacho.simulator} runs against. Rather than fabricating a finished file,
 * it speaks the same request and response sequence a real tachograph does — framing, checksums,
 * key bytes, multi-message blocks, the "response pending" delay on a big block — so the whole
 * production path is exercised: the session driver, the file assembler, the inspector, storage,
 * naming and forwarding. A bug in any of those shows up here rather than on a customer's vehicle.
 *
 * <p>The data it returns is structurally correct but synthetic. Field offsets match the Annex 1B
 * layout so the inspector reads a plausible vehicle identity out of it, and the content is
 * derived from the device id so repeated downloads of the same device are byte-identical, which
 * makes delivery and de-duplication testable.
 */
public class VirtualVehicleUnit implements VuChannel {

    private static final Logger LOGGER = LoggerFactory.getLogger(VirtualVehicleUnit.class);

    /** Marker written into the manufacturer field so a synthetic file is never mistaken for real. */
    public static final String MARKER = "DHFLEETVIEW SIMULATOR";

    private static final int CERTIFICATE_LENGTH = 194;
    private static final int SIGNATURE_LENGTH = 128;
    private static final int VIN_LENGTH = 17;

    /** Data field capacity minus the service identifier and TREP bytes. */
    private static final int PAYLOAD_PER_MESSAGE = VuMessage.MAX_DATA_LENGTH - 2;

    private final long deviceId;
    private final boolean driverCardInserted;
    private final Random random;

    private final BlockingQueue<byte[]> outbound = new LinkedBlockingQueue<>();
    private byte[] inbound = new byte[0];
    private volatile boolean open = true;

    public VirtualVehicleUnit(long deviceId, boolean driverCardInserted) {
        this.deviceId = deviceId;
        this.driverCardInserted = driverCardInserted;
        this.random = new Random(deviceId);
    }

    // -----------------------------------------------------------------------
    // VuChannel
    // -----------------------------------------------------------------------

    @Override
    public void write(byte[] data) {
        byte[] merged = new byte[inbound.length + data.length];
        System.arraycopy(inbound, 0, merged, 0, inbound.length);
        System.arraycopy(data, 0, merged, inbound.length, data.length);
        inbound = merged;

        while (inbound.length >= VuMessage.MIN_MESSAGE_LENGTH) {
            int total;
            try {
                total = VuMessage.frameLength(inbound, 0, inbound.length);
            } catch (VuProtocolException e) {
                LOGGER.warn("Simulated vehicle unit received an unframed request: {}", e.getMessage());
                inbound = new byte[0];
                return;
            }
            if (total < 0) {
                return;
            }
            try {
                handle(VuMessage.decode(inbound, 0, inbound.length));
            } catch (VuProtocolException e) {
                LOGGER.warn("Simulated vehicle unit rejected a request: {}", e.getMessage());
            }
            inbound = Arrays.copyOfRange(inbound, total, inbound.length);
        }
    }

    @Override
    public byte[] read(long timeoutMillis) throws IOException {
        try {
            byte[] next = outbound.poll(Math.max(0, timeoutMillis), TimeUnit.MILLISECONDS);
            return next != null ? next : new byte[0];
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted while reading from the simulated vehicle unit", e);
        }
    }

    @Override
    public boolean isOpen() {
        return open;
    }

    @Override
    public String getDescription() {
        return "simulated-vu-" + deviceId;
    }

    @Override
    public void close() {
        open = false;
        outbound.clear();
    }

    // -----------------------------------------------------------------------
    // Request handling
    // -----------------------------------------------------------------------

    private void handle(VuMessage request) {
        switch (request.getServiceId()) {
            case VuMessage.SID_START_COMMUNICATION ->
                    respond((byte) 0xC1, (byte) 0xEA, (byte) 0x8F);
            case VuMessage.SID_START_DIAGNOSTIC_SESSION ->
                    respond((byte) 0x50, (byte) 0x81);
            case VuMessage.SID_REQUEST_UPLOAD ->
                    respond((byte) 0x75, (byte) 0x00, (byte) 0xFF);
            case VuMessage.SID_REQUEST_TRANSFER_EXIT ->
                    respond((byte) 0x77);
            case VuMessage.SID_STOP_COMMUNICATION ->
                    respond((byte) 0xC2);
            case VuMessage.SID_TRANSFER_DATA ->
                    handleTransferData(request);
            default ->
                    respondNegative(request.getServiceId(), 0x11);
        }
    }

    private void handleTransferData(VuMessage request) {
        byte[] payload = request.getPayload();
        if (payload.length < 1) {
            respondNegative(VuMessage.SID_TRANSFER_DATA, 0x13);
            return;
        }
        TrepType trep = TrepType.fromCode(payload[0] & 0xFF);
        if (trep == null || trep.getGeneration() != 1) {
            // A generation 1 unit refuses later-generation blocks, which is how the client
            // detects which generation it is talking to.
            respondNegative(VuMessage.SID_TRANSFER_DATA, 0x12);
            return;
        }
        if (trep == TrepType.CARD_DOWNLOAD && !driverCardInserted) {
            respondNegative(VuMessage.SID_TRANSFER_DATA, 0x22);
            return;
        }

        byte[] block = buildBlock(trep, payload);
        sendBlock(trep, block);
    }

    /** Splits a block across as many messages as it needs, repeating the header on each. */
    private void sendBlock(TrepType trep, byte[] block) {
        int offset = 0;
        while (offset < block.length) {
            int chunk = Math.min(PAYLOAD_PER_MESSAGE, block.length - offset);
            byte[] data = new byte[chunk + 2];
            data[0] = (byte) (VuMessage.SID_TRANSFER_DATA + VuMessage.POSITIVE_RESPONSE_OFFSET);
            data[1] = (byte) trep.getCode();
            System.arraycopy(block, offset, data, 2, chunk);
            outbound.add(VuMessage.request(data).encode());
            offset += chunk;
        }
    }

    private void respond(byte... data) {
        outbound.add(new VuMessage(VuMessage.ADDRESS_TESTER, VuMessage.ADDRESS_VU, data).encode());
    }

    private void respondNegative(int serviceId, int code) {
        respond((byte) VuMessage.SID_NEGATIVE_RESPONSE, (byte) serviceId, (byte) code);
    }

    // -----------------------------------------------------------------------
    // Synthetic block content, laid out per the Annex 1B data dictionary
    // -----------------------------------------------------------------------

    private byte[] buildBlock(TrepType trep, byte[] requestPayload) {
        return switch (trep) {
            case OVERVIEW -> buildOverview();
            case ACTIVITIES -> buildActivities(requestPayload);
            case EVENTS_FAULTS -> buildFiller(512);
            case DETAILED_SPEED -> buildFiller(4096);
            case TECHNICAL_DATA -> buildTechnicalData();
            case CARD_DOWNLOAD -> buildFiller(2048);
            default -> buildFiller(256);
        };
    }

    private byte[] buildOverview() {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.writeBytes(pseudoRandom(CERTIFICATE_LENGTH));
        out.writeBytes(pseudoRandom(CERTIFICATE_LENGTH));
        out.writeBytes(fixed(String.format("WDB%014d", deviceId % 100000000000000L), VIN_LENGTH));
        out.write(0x11);
        out.write(0x00);
        out.writeBytes(fixed(String.format("SIM%05d", deviceId % 100000), 13));
        writeTimeReal(out, System.currentTimeMillis());
        writeTimeReal(out, System.currentTimeMillis() - 90L * 24 * 3600 * 1000);
        writeTimeReal(out, System.currentTimeMillis());
        out.write(driverCardInserted ? 0x01 : 0x00);
        out.writeBytes(pseudoRandom(256));
        out.writeBytes(pseudoRandom(SIGNATURE_LENGTH));
        return out.toByteArray();
    }

    private byte[] buildTechnicalData() {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(0x00);
        out.writeBytes(fixed(MARKER, 35));
        out.write(0x00);
        out.writeBytes(fixed("SIMULATED - NOT REAL TACHOGRAPH DATA", 35));
        out.writeBytes(fixed("SIMVU-650", 16));
        long serial = 1000000 + (deviceId % 900000);
        out.write((int) (serial >> 24));
        out.write((int) (serial >> 16));
        out.write((int) (serial >> 8));
        out.write((int) serial);
        out.write(0x01);
        out.write(0x26);
        out.write(0x01);
        out.write(0x0A);
        out.writeBytes(pseudoRandom(128));
        out.writeBytes(pseudoRandom(SIGNATURE_LENGTH));
        return out.toByteArray();
    }

    /**
     * Activity data for one day. Weekends produce an almost empty block, which mirrors a real
     * vehicle and gives the pipeline short blocks to handle as well as long ones.
     */
    private byte[] buildActivities(byte[] requestPayload) {
        long seconds = 0;
        if (requestPayload.length >= 5) {
            seconds = ((long) (requestPayload[1] & 0xFF) << 24)
                    | ((long) (requestPayload[2] & 0xFF) << 16)
                    | ((long) (requestPayload[3] & 0xFF) << 8)
                    | (requestPayload[4] & 0xFF);
        }
        long day = seconds / 86400L;
        boolean restDay = day % 7 == 5 || day % 7 == 6;

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        writeTimeReal(out, seconds * 1000L);
        out.writeBytes(pseudoRandom(restDay ? 48 : 700 + (int) (day % 400)));
        out.writeBytes(pseudoRandom(SIGNATURE_LENGTH));
        return out.toByteArray();
    }

    private byte[] buildFiller(int length) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.writeBytes(pseudoRandom(length));
        out.writeBytes(pseudoRandom(SIGNATURE_LENGTH));
        return out.toByteArray();
    }

    private void writeTimeReal(ByteArrayOutputStream out, long millis) {
        long seconds = millis / 1000L;
        out.write((int) (seconds >> 24));
        out.write((int) (seconds >> 16));
        out.write((int) (seconds >> 8));
        out.write((int) seconds);
    }

    /** A fixed-length regulation string, space padded. */
    private byte[] fixed(String value, int length) {
        byte[] field = new byte[length];
        Arrays.fill(field, (byte) 0x20);
        byte[] source = value.getBytes(StandardCharsets.ISO_8859_1);
        System.arraycopy(source, 0, field, 0, Math.min(source.length, length));
        return field;
    }

    /** Deterministic filler standing in for certificate and record content. */
    private byte[] pseudoRandom(int length) {
        byte[] data = new byte[length];
        random.nextBytes(data);
        return data;
    }
}
