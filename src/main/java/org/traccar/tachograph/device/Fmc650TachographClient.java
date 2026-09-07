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
import org.traccar.database.CommandsManager;
import org.traccar.model.Command;
import org.traccar.model.TachographDownloadJob;
import org.traccar.session.ConnectionManager;
import org.traccar.tachograph.TachographDeviceClient;
import org.traccar.tachograph.TachographDownloadRequest;
import org.traccar.tachograph.TachographDownloadResult;
import org.traccar.tachograph.TachographException;
import org.traccar.tachograph.tunnel.TachographTunnelRegistry;
import org.traccar.tachograph.tunnel.TunnelConnection;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

/**
 * Downloads tachograph data from a real vehicle unit through the data tunnel an FMC650 opens
 * to {@link org.traccar.tachograph.tunnel.TachographTunnelServer}.
 *
 * <p>This class owns getting to a usable tunnel — asking the device to open one, waiting for it,
 * and taking exclusive use of it. Everything after that is {@link VuDownloadRunner}, which the
 * simulator shares.
 */
@Singleton
public class Fmc650TachographClient implements TachographDeviceClient {

    private static final Logger LOGGER = LoggerFactory.getLogger(Fmc650TachographClient.class);

    /** How often to check whether the device has brought its tunnel up. */
    private static final long TUNNEL_POLL_MILLIS = 1000;

    private final Config config;
    private final TachographTunnelRegistry registry;
    private final ConnectionManager connectionManager;
    private final CommandsManager commandsManager;
    private final VuDownloadRunner runner;

    @Inject
    public Fmc650TachographClient(
            Config config,
            TachographTunnelRegistry registry,
            ConnectionManager connectionManager,
            CommandsManager commandsManager,
            VuDownloadRunner runner) {
        this.config = config;
        this.registry = registry;
        this.connectionManager = connectionManager;
        this.commandsManager = commandsManager;
        this.runner = runner;
    }

    @Override
    public String getClientType() {
        return CLIENT_FMC650;
    }

    @Override
    public boolean canHandle(long deviceId) {
        return config.getInteger(Keys.TACHO_TUNNEL_PORT) > 0;
    }

    @Override
    public TachographDownloadResult download(TachographDownloadRequest request) throws TachographException {

        TunnelConnection tunnel = obtainTunnel(request);
        if (!tunnel.tryAcquire()) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_ALREADY_RUNNING,
                    "Another download is already using the tunnel for device " + request.getDeviceId());
        }
        try {
            return runner.run(tunnel, request, CLIENT_FMC650);
        } finally {
            tunnel.release();
        }
    }

    /**
     * Returns an open tunnel for the device, telling the device to open one if it has not already.
     */
    private TunnelConnection obtainTunnel(TachographDownloadRequest request) throws TachographException {
        long deviceId = request.getDeviceId();

        TunnelConnection existing = registry.get(deviceId);
        if (existing != null) {
            LOGGER.debug("Reusing the open tachograph tunnel for device {}", deviceId);
            return existing;
        }

        if (connectionManager.getDeviceSession(deviceId) == null) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_DEVICE_OFFLINE,
                    "Device " + deviceId + " has no tracking connection, so it cannot be asked to "
                            + "open a tachograph tunnel");
        }

        sendTriggerCommand(deviceId);
        request.getProgressListener().onProgress(5, "Waiting for the vehicle to connect");

        long waitSeconds = config.getInteger(Keys.TACHO_TUNNEL_WAIT);
        long deadline = System.currentTimeMillis() + waitSeconds * 1000L;
        while (System.currentTimeMillis() < deadline) {
            TunnelConnection tunnel = registry.get(deviceId);
            if (tunnel != null) {
                LOGGER.info("Device {} opened its tachograph tunnel", deviceId);
                return tunnel;
            }
            try {
                Thread.sleep(TUNNEL_POLL_MILLIS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new TachographException(
                        TachographDownloadJob.ERROR_DOWNLOAD_TIMEOUT, "Download interrupted");
            }
        }

        throw new TachographException(
                TachographDownloadJob.ERROR_DEVICE_OFFLINE, String.format(
                        "Device %d did not open its tachograph tunnel within %d s",
                        deviceId, waitSeconds));
    }

    /**
     * Tells the device to open its tunnel. The command text is configuration rather than code
     * because it differs between FMC650 firmware builds and between installations; leaving it
     * unset suits a fleet whose devices connect on their own schedule.
     */
    private void sendTriggerCommand(long deviceId) throws TachographException {
        String text = config.getString(Keys.TACHO_TRIGGER_COMMAND);
        if (text == null || text.isBlank()) {
            LOGGER.debug("No tacho.triggerCommand is configured; waiting for device {} to connect "
                    + "on its own schedule", deviceId);
            return;
        }
        Command command = new Command();
        command.setDeviceId(deviceId);
        command.setType(Command.TYPE_CUSTOM);
        command.set(Command.KEY_DATA, text);
        try {
            commandsManager.sendCommand(command);
            LOGGER.info("Sent the tachograph tunnel trigger to device {}", deviceId);
        } catch (Exception e) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_PROTOCOL,
                    "Could not send the tachograph trigger command to device " + deviceId
                            + ": " + e.getMessage(), e);
        }
    }
}
