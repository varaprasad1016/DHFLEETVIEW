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

/**
 * Retrieves a tachograph DDD file from a vehicle.
 *
 * <p>Two implementations exist: {@link org.traccar.tachograph.device.Fmc650TachographClient},
 * which drives a real vehicle unit over the FMC650 data tunnel, and
 * {@link SimulatedTachographDeviceClient}, which answers from a built-in vehicle-unit emulator
 * so the whole pipeline can be exercised without hardware.
 */
public interface TachographDeviceClient {

    String CLIENT_SIMULATED = "SIMULATED";
    String CLIENT_FMC650 = "FMC650";

    String getClientType();

    /**
     * Performs one download attempt.
     *
     * @return the DDD bytes with metadata
     * @throws TachographException with a stable error code from
     *         {@link org.traccar.model.TachographDownloadJob}
     */
    TachographDownloadResult download(TachographDownloadRequest request) throws TachographException;

    /** Whether this client can serve the given device. */
    boolean canHandle(long deviceId);
}
