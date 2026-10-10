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
package org.traccar.tachograph;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.TachographDownloadJob;
import org.traccar.tachograph.device.VirtualVehicleUnit;
import org.traccar.tachograph.device.VuDownloadRunner;
import org.traccar.tachograph.protocol.VuTimings;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.Locale;

/**
 * Runs a download against a built-in vehicle-unit emulator instead of real hardware.
 *
 * <p>TEST AND DEMONSTRATION ONLY. The files it produces are structurally correct but synthetic,
 * and their technical-data block is stamped with {@link VirtualVehicleUnit#MARKER} so one can
 * never be mistaken for a real tachograph record. Never enable {@code tacho.simulator} on a
 * production server.
 *
 * <p>What makes it worth having is that it is not a shortcut: it drives the same
 * {@link VuDownloadRunner} the FMC650 client uses, over a channel that speaks the real Annex 1B
 * protocol. A regression in framing, block assembly, file naming or delivery fails here first.
 *
 * <p>Set the {@code tacho.simulator.behaviour} system property to
 * {@code OFFLINE}, {@code TIMEOUT}, {@code INVALID_FILE}, {@code NO_CARD} or {@code DEVICE_ERROR}
 * to rehearse the failure paths and their retry behaviour.
 */
@Singleton
public class SimulatedTachographDeviceClient implements TachographDeviceClient {

    private static final Logger LOGGER = LoggerFactory.getLogger(SimulatedTachographDeviceClient.class);

    /** Kept for compatibility with earlier fixtures that searched files for this text. */
    public static final String MARKER = VirtualVehicleUnit.MARKER;

    /** The emulator answers instantly, so the protocol timings can be tight. */
    private static final VuTimings SIMULATOR_TIMINGS = VuTimings.of(2000, 60, 2000, 60000, 2);

    /** Which failure the simulator should stage instead of a successful download. */
    public enum SimulatedBehaviour {
        SUCCESS,
        OFFLINE,
        TIMEOUT,
        INVALID_FILE,
        NO_CARD,
        DEVICE_ERROR
    }

    private final Config config;
    private final VuDownloadRunner runner;

    @Inject
    public SimulatedTachographDeviceClient(Config config, VuDownloadRunner runner) {
        this.config = config;
        this.runner = runner;
    }

    @Override
    public String getClientType() {
        return CLIENT_SIMULATED;
    }

    @Override
    public boolean canHandle(long deviceId) {
        return Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_SIMULATOR));
    }

    @Override
    public TachographDownloadResult download(TachographDownloadRequest request) throws TachographException {

        SimulatedBehaviour behaviour = resolveBehaviour();
        LOGGER.info("Simulated {} download for device {}, staging {}",
                request.getDownloadType(), request.getDeviceId(), behaviour);

        switch (behaviour) {
            case OFFLINE -> throw new TachographException(
                    TachographDownloadJob.ERROR_DEVICE_OFFLINE, "Simulated device offline");
            case TIMEOUT -> throw new TachographException(
                    TachographDownloadJob.ERROR_DOWNLOAD_TIMEOUT, "Simulated download timeout");
            case DEVICE_ERROR -> throw new TachographException(
                    TachographDownloadJob.ERROR_PROTOCOL, "Simulated vehicle unit protocol error");
            case INVALID_FILE -> throw new TachographException(
                    TachographDownloadJob.ERROR_INVALID_FILE,
                    "Simulated vehicle unit returned an unusable file");
            default -> {
                boolean cardInserted = behaviour != SimulatedBehaviour.NO_CARD;
                try (VirtualVehicleUnit unit = new VirtualVehicleUnit(request.getDeviceId(), cardInserted)) {
                    return runner.run(unit, request, CLIENT_SIMULATED, SIMULATOR_TIMINGS);
                }
            }
        }
    }

    private SimulatedBehaviour resolveBehaviour() {
        String value = System.getProperty("tacho.simulator.behaviour");
        if (value != null && !value.isBlank()) {
            try {
                return SimulatedBehaviour.valueOf(value.trim().toUpperCase(Locale.ROOT));
            } catch (IllegalArgumentException e) {
                LOGGER.warn("Unknown tacho.simulator.behaviour '{}', running a successful download", value);
            }
        }
        return SimulatedBehaviour.SUCCESS;
    }
}
