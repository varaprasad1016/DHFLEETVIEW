/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.tachograph;

/**
 * Client that talks to an FMC650 to retrieve a tachograph DDD file.
 *
 * <p>Implementations are intentionally narrow: the ONLY supported device is FMC650.
 * The production implementation requires the still-missing Teltonika/tachograph
 * protocol documentation (see docs/tachograph/FMC650-INTEGRATION.md). Until that
 * documentation is available, use {@link SimulatedTachographDeviceClient}.
 */
public interface TachographDeviceClient {

    String CLIENT_SIMULATED = "SIMULATED";
    String CLIENT_FMC650 = "FMC650";

    String getClientType();

    /**
     * Performs one download attempt for the given job.
     *
     * @param deviceId     Traccar device id (FMC650)
     * @param downloadType {@link org.traccar.model.TachographDownloadJob#TYPE_DRIVER} or TYPE_VEHICLE
     * @return the raw DDD bytes with metadata, or throws
     * @throws TachographException with a stable error code
     */
    TachographDownloadResult download(long deviceId, String downloadType) throws TachographException;

    /**
     * Whether this client can handle the given device. The simulated client
     * handles any device; the real FMC650 client checks the device model.
     */
    boolean canHandle(long deviceId);
}
