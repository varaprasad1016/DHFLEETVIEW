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
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.TachographDownloadJob;
import org.traccar.tachograph.TachographDeviceClient;
import org.traccar.tachograph.TachographDownloadRequest;
import org.traccar.tachograph.TachographDownloadResult;
import org.traccar.tachograph.TachographException;
import org.traccar.tachograph.protocol.ContinuationMode;
import org.traccar.tachograph.protocol.DddFileBuilder;
import org.traccar.tachograph.protocol.DddInspector;
import org.traccar.tachograph.protocol.DddMetadata;
import org.traccar.tachograph.protocol.TrepType;
import org.traccar.tachograph.protocol.VuChannel;
import org.traccar.tachograph.protocol.VuDownloadSession;
import org.traccar.tachograph.protocol.VuProtocolException;
import org.traccar.tachograph.protocol.VuTimings;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.io.IOException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

/**
 * Runs a complete download over any {@link VuChannel} and turns it into a stored-file result.
 *
 * <p>Both device clients share this: the FMC650 client supplies a live tunnel and the simulator
 * supplies a {@link VirtualVehicleUnit}. Keeping one implementation means the simulator is a
 * genuine rehearsal of production rather than a parallel code path that can drift away from it.
 */
@Singleton
public class VuDownloadRunner {

    private static final Logger LOGGER = LoggerFactory.getLogger(VuDownloadRunner.class);

    /** Progress percentage once the handshake is done and before any block has arrived. */
    private static final int PROGRESS_HANDSHAKE = 15;
    /** Progress percentage when the transfer is complete and storage begins. */
    private static final int PROGRESS_TRANSFER_COMPLETE = 90;

    private final Config config;

    @Inject
    public VuDownloadRunner(Config config) {
        this.config = config;
    }

    /**
     * Drives one download to completion.
     *
     * @param channel    an open channel to the vehicle unit; the caller owns and closes it
     * @param request    what to download and where to report progress
     * @param clientType the client label recorded against the resulting file
     */
    public TachographDownloadResult run(
            VuChannel channel, TachographDownloadRequest request, String clientType)
            throws TachographException {
        return run(channel, request, clientType, buildTimings());
    }

    /**
     * Drives one download using explicit timings. The simulator uses this to run at emulator
     * speed rather than waiting out the mobile-network allowances a real vehicle needs.
     */
    public TachographDownloadResult run(
            VuChannel channel, TachographDownloadRequest request, String clientType, VuTimings timings)
            throws TachographException {

        DddFileBuilder builder = new DddFileBuilder();
        ContinuationMode continuationMode =
                ContinuationMode.parse(config.getString(Keys.TACHO_VU_CONTINUATION_MODE));

        try (VuDownloadSession session =
                     new VuDownloadSession(channel, timings, (trep, bytes) -> { }, continuationMode)) {

            session.open();
            request.getProgressListener().onProgress(PROGRESS_HANDSHAKE, "Connected to the vehicle unit");

            if (TachographDownloadJob.TYPE_DRIVER.equals(request.getDownloadType())) {
                downloadDriverCard(session, builder, request);
            } else {
                downloadVehicleUnit(session, builder, request);
            }

        } catch (VuProtocolException e) {
            throw new TachographException(TachographDownloadJob.ERROR_PROTOCOL, e.getMessage(), e);
        } catch (IOException e) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_DEVICE_OFFLINE,
                    "Connection to device " + request.getDeviceId() + " failed: " + e.getMessage(), e);
        }

        if (builder.isEmpty() || builder.size() < 4) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_INVALID_FILE,
                    "The vehicle unit on device " + request.getDeviceId()
                            + " returned " + builder.size() + " bytes");
        }

        byte[] data = builder.toByteArray();
        try {
            DddInspector.validateStructure(data);
        } catch (VuProtocolException e) {
            throw new TachographException(TachographDownloadJob.ERROR_INVALID_FILE, e.getMessage(), e);
        }

        DddMetadata metadata = DddInspector.inspect(data, builder.getBlocks());
        request.getProgressListener().onProgress(PROGRESS_TRANSFER_COMPLETE, "Transfer complete");

        TachographDownloadResult result = new TachographDownloadResult(
                data, buildFileName(request, metadata), request.getDownloadType(), new Date());
        result.setMetadata(metadata);
        result.setClientType(clientType);

        LOGGER.info("Downloaded {} bytes of {} data from device {} in {} block(s) via {}",
                data.length, request.getDownloadType(), request.getDeviceId(),
                builder.getBlocks().size(), clientType);
        return result;
    }

    // -----------------------------------------------------------------------
    // Block sequencing
    // -----------------------------------------------------------------------

    private void downloadVehicleUnit(
            VuDownloadSession session, DddFileBuilder builder, TachographDownloadRequest request)
            throws VuProtocolException, IOException {

        int generation = detectGeneration(session, builder);
        boolean includeSpeed = config.getBoolean(Keys.TACHO_INCLUDE_SPEED);
        List<TrepType> sequence = TrepType.vehicleSequence(generation, includeSpeed);
        List<Date> days = resolveDays(request);

        int totalSteps = 0;
        for (TrepType trep : sequence) {
            totalSteps += trep.isDateRanged() ? days.size() : 1;
        }

        int completedSteps = 0;
        int activityDay = 0;
        for (TrepType trep : sequence) {
            if (builder.contains(trep)) {
                // The overview arrived while detecting the generation; do not fetch it twice.
                completedSteps++;
                continue;
            }
            if (trep.isDateRanged()) {
                for (Date day : days) {
                    builder.append(trep, day, session.downloadBlock(trep, day));
                    completedSteps++;
                    activityDay++;
                    reportProgress(request, completedSteps, totalSteps,
                            String.format("Activities, day %d of %d", activityDay, days.size()));
                }
            } else {
                builder.append(trep, null, session.downloadBlock(trep, null));
                completedSteps++;
                reportProgress(request, completedSteps, totalSteps, trep.getLabel());
            }
        }
    }

    private void downloadDriverCard(
            VuDownloadSession session, DddFileBuilder builder, TachographDownloadRequest request)
            throws VuProtocolException, IOException, TachographException {

        request.getProgressListener().onProgress(30, "Reading the inserted driver card");
        byte[] block;
        try {
            block = session.downloadBlock(TrepType.CARD_DOWNLOAD, null);
        } catch (VuProtocolException e) {
            if (e.getNegativeResponseCode() >= 0) {
                throw new TachographException(
                        TachographDownloadJob.ERROR_CARD_UNAVAILABLE,
                        "The vehicle unit on device " + request.getDeviceId()
                                + " has no readable driver card inserted", e);
            }
            throw e;
        }
        if (block.length == 0) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_CARD_UNAVAILABLE,
                    "No driver card is inserted in the vehicle unit on device " + request.getDeviceId());
        }
        builder.append(TrepType.CARD_DOWNLOAD, null, block);
    }

    /**
     * Identifies the vehicle unit generation by asking for each generation's overview block in
     * turn. The block that succeeds is kept, so probing costs no extra transfer.
     */
    private int detectGeneration(VuDownloadSession session, DddFileBuilder builder)
            throws VuProtocolException, IOException {

        VuProtocolException lastFailure = null;
        for (TrepType overview : List.of(TrepType.OVERVIEW, TrepType.OVERVIEW_G2, TrepType.OVERVIEW_G2V2)) {
            try {
                byte[] block = session.downloadBlock(overview, null);
                if (block.length > 0) {
                    builder.append(overview, null, block);
                    LOGGER.debug("Vehicle unit identified as generation {}", overview.getGeneration());
                    return overview.getGeneration();
                }
            } catch (VuProtocolException e) {
                if (e.getNegativeResponseCode() < 0) {
                    throw e;
                }
                lastFailure = e;
                LOGGER.debug("Overview block {} refused; trying the next generation", overview.getLabel());
            }
        }
        throw lastFailure != null ? lastFailure
                : new VuProtocolException("The vehicle unit returned no overview block");
    }

    /**
     * The calendar days to request activity data for, each at midnight UTC because that is what
     * the regulation's date parameter selects.
     */
    private List<Date> resolveDays(TachographDownloadRequest request) {
        LocalDate end = request.getTo() != null
                ? request.getTo().toInstant().atZone(ZoneOffset.UTC).toLocalDate()
                : LocalDate.now(ZoneOffset.UTC);
        LocalDate start;
        if (request.getFrom() != null) {
            start = request.getFrom().toInstant().atZone(ZoneOffset.UTC).toLocalDate();
        } else {
            start = end.minusDays(Math.max(1, config.getInteger(Keys.TACHO_ACTIVITY_DAYS)) - 1L);
        }
        if (start.isAfter(end)) {
            start = end;
        }

        List<Date> days = new ArrayList<>();
        for (LocalDate day = start; !day.isAfter(end); day = day.plusDays(1)) {
            days.add(Date.from(day.atStartOfDay(ZoneOffset.UTC).toInstant()));
        }
        return days;
    }

    private void reportProgress(
            TachographDownloadRequest request, int completed, int total, String detail) {
        int span = PROGRESS_TRANSFER_COMPLETE - PROGRESS_HANDSHAKE;
        int percent = PROGRESS_HANDSHAKE + (total > 0 ? completed * span / total : span);
        request.getProgressListener().onProgress(Math.min(percent, PROGRESS_TRANSFER_COMPLETE), detail);
    }

    /**
     * Names the file so an analysis bureau can identify it without opening it: a type letter,
     * the vehicle registration or card number, and the download time.
     */
    private String buildFileName(TachographDownloadRequest request, DddMetadata metadata) {
        boolean driver = TachographDownloadJob.TYPE_DRIVER.equals(request.getDownloadType());
        String identity = driver ? metadata.getCardNumber() : metadata.getVehicleRegistrationNumber();
        if (identity == null || identity.isBlank()) {
            identity = String.valueOf(request.getDeviceId());
        }
        String safeIdentity = identity.replaceAll("[^A-Za-z0-9]", "");
        String timestamp = String.format("%tY%<tm%<td%<tH%<tM%<tS",
                Date.from(Instant.now().truncatedTo(ChronoUnit.SECONDS)));
        return String.format("%s_%s_%s.DDD", driver ? "C" : "M", safeIdentity, timestamp);
    }

    private VuTimings buildTimings() {
        return VuTimings.of(
                config.getInteger(Keys.TACHO_VU_RESPONSE_TIMEOUT),
                config.getInteger(Keys.TACHO_VU_BLOCK_IDLE),
                config.getInteger(Keys.TACHO_VU_PENDING_EXTENSION),
                config.getInteger(Keys.TACHO_VU_BLOCK_TIMEOUT),
                config.getInteger(Keys.TACHO_VU_MAX_ATTEMPTS));
    }

    /** The client label used for files produced by the simulator. */
    public static String simulatedClientType() {
        return TachographDeviceClient.CLIENT_SIMULATED;
    }
}
