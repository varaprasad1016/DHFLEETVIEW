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

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Arrays;
import java.util.Date;

/**
 * Drives one vehicle-unit download session over a {@link VuChannel}.
 *
 * <p>The sequence follows Annex 1B Appendix 7:
 * <ol>
 *   <li>{@code StartCommunication} (0x81) — the vehicle unit answers with its key bytes.</li>
 *   <li>{@code StartDiagnosticSession} (0x10 0x81) — enters the download session.</li>
 *   <li>{@code RequestUpload} (0x35) — the vehicle unit agrees to transfer data.</li>
 *   <li>{@code TransferData} (0x36 TREP) once per data block, repeated per day for activities.</li>
 *   <li>{@code RequestTransferExit} (0x37) then {@code StopCommunication} (0x82).</li>
 * </ol>
 *
 * <p>This class is not thread-safe; one instance serves exactly one download job.
 */
public class VuDownloadSession implements AutoCloseable {

    private static final Logger LOGGER = LoggerFactory.getLogger(VuDownloadSession.class);

    /**
     * Fixed {@code RequestUpload} parameters from Annex 1B Appendix 7: format 0x00, address
     * 0x000000, and an unbounded size of 0xFFFFFF. The vehicle unit ignores the address and
     * returns the blocks selected by the subsequent {@code TransferData} requests.
     */
    private static final byte[] REQUEST_UPLOAD_PARAMETERS = {
        0x00, 0x00, 0x00, 0x00, 0x00, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF,
    };

    /** Callback used to report byte counts while a block is streaming in. */
    public interface ProgressListener {
        void onProgress(TrepType trep, long bytesSoFar);
    }

    private final VuChannel channel;
    private final VuTimings timings;
    private final ProgressListener progressListener;
    private final ContinuationMode continuationMode;

    private byte[] buffer = new byte[0];
    private byte[] keyBytes = new byte[0];
    private boolean communicationStarted;
    private boolean uploadRequested;

    public VuDownloadSession(VuChannel channel, VuTimings timings, ProgressListener progressListener) {
        this(channel, timings, progressListener, ContinuationMode.REPEAT_HEADER);
    }

    public VuDownloadSession(
            VuChannel channel, VuTimings timings, ProgressListener progressListener,
            ContinuationMode continuationMode) {
        this.channel = channel;
        this.timings = timings != null ? timings : VuTimings.defaults();
        this.progressListener = progressListener != null ? progressListener : (trep, bytes) -> { };
        this.continuationMode = continuationMode != null ? continuationMode : ContinuationMode.REPEAT_HEADER;
    }

    /**
     * Performs the handshake: start communication, enter the diagnostic session and request upload.
     * Must be called before any {@link #downloadBlock}.
     */
    public void open() throws VuProtocolException, IOException {
        VuMessage started = exchange(
                VuMessage.request((byte) VuMessage.SID_START_COMMUNICATION),
                VuMessage.SID_START_COMMUNICATION);
        keyBytes = started.getPayload();
        communicationStarted = true;
        LOGGER.debug("Vehicle unit {} start communication, key bytes {}",
                channel.getDescription(), toHex(keyBytes));

        // 0x81 selects the "download" diagnostic session defined by the regulation.
        exchange(
                VuMessage.request((byte) VuMessage.SID_START_DIAGNOSTIC_SESSION, (byte) 0x81),
                VuMessage.SID_START_DIAGNOSTIC_SESSION);
        LOGGER.debug("Vehicle unit {} diagnostic session started", channel.getDescription());

        byte[] uploadRequest = new byte[1 + REQUEST_UPLOAD_PARAMETERS.length];
        uploadRequest[0] = (byte) VuMessage.SID_REQUEST_UPLOAD;
        System.arraycopy(REQUEST_UPLOAD_PARAMETERS, 0, uploadRequest, 1, REQUEST_UPLOAD_PARAMETERS.length);
        exchange(VuMessage.request(uploadRequest), VuMessage.SID_REQUEST_UPLOAD);
        uploadRequested = true;
        LOGGER.debug("Vehicle unit {} accepted upload request", channel.getDescription());
    }

    /** The key bytes returned by {@code StartCommunication}, useful for diagnostics. */
    public byte[] getKeyBytes() {
        return Arrays.copyOf(keyBytes, keyBytes.length);
    }

    /**
     * Requests one data block and collects every sub-message the vehicle unit sends for it.
     *
     * @param trep the block to request
     * @param day  for date-ranged blocks (activities) the calendar day to download; ignored otherwise
     * @return the concatenated response data fields, each still prefixed by {@code 0x76 TREP},
     *         which is exactly the byte sequence a DDD file contains for this block
     */
    public byte[] downloadBlock(TrepType trep, Date day) throws VuProtocolException, IOException {
        if (!uploadRequested) {
            throw new VuProtocolException("downloadBlock called before open()");
        }

        byte[] request;
        if (trep.isDateRanged()) {
            if (day == null) {
                throw new VuProtocolException("TREP " + trep.getLabel() + " requires a calendar day");
            }
            // TimeReal: seconds since 1970-01-01 00:00:00 UTC, big endian, four bytes.
            long seconds = day.getTime() / 1000L;
            request = new byte[] {
                (byte) VuMessage.SID_TRANSFER_DATA, (byte) trep.getCode(),
                (byte) (seconds >> 24), (byte) (seconds >> 16), (byte) (seconds >> 8), (byte) seconds,
            };
        } else {
            request = new byte[] {(byte) VuMessage.SID_TRANSFER_DATA, (byte) trep.getCode()};
        }

        VuMessage first = exchange(VuMessage.request(request), VuMessage.SID_TRANSFER_DATA);

        ByteArrayOutputStream block = new ByteArrayOutputStream();
        writeMessageData(block, first, trep, true);
        progressListener.onProgress(trep, block.size());

        // Sub-messages follow without a further request. The block ends when the vehicle unit
        // goes idle for longer than the configured gap, or when a frame arrives that is not a
        // TransferData positive response.
        long hardDeadline = System.currentTimeMillis() + timings.getTotalBlockTimeoutMillis();
        while (true) {
            if (System.currentTimeMillis() > hardDeadline) {
                throw new VuProtocolException(String.format(
                        "Vehicle unit %s exceeded the %d ms ceiling while sending %s (%d bytes so far)",
                        channel.getDescription(), timings.getTotalBlockTimeoutMillis(),
                        trep.getLabel(), block.size()));
            }

            VuMessage next = readMessage(System.currentTimeMillis() + timings.getBlockIdleMillis());
            if (next == null) {
                break;
            }
            if (next.isNegativeResponse()) {
                int code = next.getNegativeResponseCode();
                if (code == VuMessage.NRC_RESPONSE_PENDING) {
                    hardDeadline = Math.max(hardDeadline,
                            System.currentTimeMillis() + timings.getPendingExtensionMillis());
                    continue;
                }
                throw new VuProtocolException(String.format(
                        "Vehicle unit %s rejected %s with negative response code 0x%02X",
                        channel.getDescription(), trep.getLabel(), code), code);
            }
            if (!next.isPositiveResponseTo(VuMessage.SID_TRANSFER_DATA)) {
                throw new VuProtocolException(String.format(
                        "Unexpected service identifier 0x%02X while receiving %s",
                        next.getServiceId(), trep.getLabel()));
            }
            writeMessageData(block, next, trep, false);
            progressListener.onProgress(trep, block.size());
        }

        byte[] result = block.toByteArray();
        LOGGER.debug("Vehicle unit {} delivered {} bytes for {}",
                channel.getDescription(), result.length, trep.getLabel());
        return result;
    }

    /**
     * Ends the transfer cleanly. Safe to call more than once and safe to call after a failure —
     * errors here are logged rather than thrown so they cannot mask the original problem.
     */
    @Override
    public void close() {
        if (uploadRequested) {
            try {
                exchange(
                        VuMessage.request((byte) VuMessage.SID_REQUEST_TRANSFER_EXIT),
                        VuMessage.SID_REQUEST_TRANSFER_EXIT);
            } catch (Exception e) {
                LOGGER.debug("Transfer exit failed for {}: {}", channel.getDescription(), e.getMessage());
            }
            uploadRequested = false;
        }
        if (communicationStarted) {
            try {
                exchange(
                        VuMessage.request((byte) VuMessage.SID_STOP_COMMUNICATION),
                        VuMessage.SID_STOP_COMMUNICATION);
            } catch (Exception e) {
                LOGGER.debug("Stop communication failed for {}: {}", channel.getDescription(), e.getMessage());
            }
            communicationStarted = false;
        }
    }

    // -----------------------------------------------------------------------
    // Framing
    // -----------------------------------------------------------------------

    /**
     * Sends a request and waits for its positive response, absorbing {@code responsePending}
     * negative responses and repeating the request on {@code busyRepeatRequest}.
     */
    private VuMessage exchange(VuMessage request, int expectedServiceId)
            throws VuProtocolException, IOException {

        VuProtocolException lastFailure = null;
        for (int attempt = 1; attempt <= timings.getMaxRequestAttempts(); attempt++) {
            channel.write(request.encode());

            long deadline = System.currentTimeMillis() + timings.getResponseTimeoutMillis();
            while (true) {
                VuMessage response = readMessage(deadline);
                if (response == null) {
                    lastFailure = new VuProtocolException(String.format(
                            "Vehicle unit %s did not answer service 0x%02X within %d ms (attempt %d/%d)",
                            channel.getDescription(), expectedServiceId,
                            timings.getResponseTimeoutMillis(), attempt, timings.getMaxRequestAttempts()));
                    break;
                }
                if (response.isNegativeResponse()) {
                    int code = response.getNegativeResponseCode();
                    if (code == VuMessage.NRC_RESPONSE_PENDING) {
                        deadline = System.currentTimeMillis() + timings.getPendingExtensionMillis();
                        continue;
                    }
                    if (code == VuMessage.NRC_BUSY_REPEAT_REQUEST) {
                        lastFailure = new VuProtocolException(String.format(
                                "Vehicle unit %s busy on service 0x%02X (attempt %d/%d)",
                                channel.getDescription(), expectedServiceId,
                                attempt, timings.getMaxRequestAttempts()), code);
                        break;
                    }
                    throw new VuProtocolException(String.format(
                            "Vehicle unit %s rejected service 0x%02X with response code 0x%02X",
                            channel.getDescription(), expectedServiceId, code), code);
                }
                if (!response.isPositiveResponseTo(expectedServiceId)) {
                    throw new VuProtocolException(String.format(
                            "Vehicle unit %s answered service 0x%02X with unexpected identifier 0x%02X",
                            channel.getDescription(), expectedServiceId, response.getServiceId()));
                }
                return response;
            }
        }
        throw lastFailure != null ? lastFailure : new VuProtocolException(
                String.format("Service 0x%02X failed on %s", expectedServiceId, channel.getDescription()));
    }

    /**
     * Reads one framed message, blocking until {@code deadline}. Returns null on timeout.
     * Leading bytes that cannot begin a valid header are discarded so a garbled frame does
     * not desynchronise the rest of the session.
     */
    private VuMessage readMessage(long deadline) throws VuProtocolException, IOException {
        while (true) {
            resynchronise();

            if (buffer.length >= 4) {
                int total = VuMessage.frameLength(buffer, 0, buffer.length);
                if (total > 0) {
                    VuMessage message = VuMessage.decode(buffer, 0, buffer.length);
                    buffer = Arrays.copyOfRange(buffer, total, buffer.length);
                    return message;
                }
            }

            long remaining = deadline - System.currentTimeMillis();
            if (remaining <= 0) {
                return null;
            }
            byte[] chunk = channel.read(Math.min(remaining, 1000L));
            if (chunk.length > 0) {
                byte[] merged = new byte[buffer.length + chunk.length];
                System.arraycopy(buffer, 0, merged, 0, buffer.length);
                System.arraycopy(chunk, 0, merged, buffer.length, chunk.length);
                buffer = merged;
            }
        }
    }

    /** Drops bytes before the next plausible format byte. */
    private void resynchronise() {
        int skip = 0;
        while (skip < buffer.length && (buffer[skip] & 0xFF) != VuMessage.FORMAT) {
            skip++;
        }
        if (skip > 0) {
            LOGGER.debug("Discarded {} unframed byte(s) from {}", skip, channel.getDescription());
            buffer = Arrays.copyOfRange(buffer, skip, buffer.length);
        }
    }

    /**
     * Appends one response message to the block being assembled.
     *
     * <p>The first message contributes its whole data field, which is the {@code 0x76 TREP}
     * prefix a DDD file starts each block with. Continuation messages contribute payload only:
     * under {@link ContinuationMode#REPEAT_HEADER} the repeated prefix is stripped, and under
     * {@link ContinuationMode#RAW_CONTINUATION} there is none to strip.
     */
    private void writeMessageData(
            ByteArrayOutputStream block, VuMessage message, TrepType trep, boolean firstMessage) {

        byte[] data = message.getData();
        int offset = 0;
        if (!firstMessage && continuationMode == ContinuationMode.REPEAT_HEADER
                && data.length >= 2
                && (data[0] & 0xFF) == VuMessage.SID_TRANSFER_DATA + VuMessage.POSITIVE_RESPONSE_OFFSET
                && (data[1] & 0xFF) == trep.getCode()) {
            offset = 2;
        }
        block.write(data, offset, data.length - offset);
    }

    private static String toHex(byte[] data) {
        StringBuilder builder = new StringBuilder(data.length * 2);
        for (byte b : data) {
            builder.append(String.format("%02X", b));
        }
        return builder.toString();
    }
}
