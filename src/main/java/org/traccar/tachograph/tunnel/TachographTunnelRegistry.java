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
package org.traccar.tachograph.tunnel;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import jakarta.inject.Singleton;

import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Tracks which devices currently have a tachograph tunnel open.
 *
 * <p>The download worker asks this registry for a device's tunnel; the Netty handler registers
 * and deregisters connections as they come and go. A device that reconnects replaces its earlier
 * connection, which is closed so a stale socket cannot answer a later download.
 */
@Singleton
public class TachographTunnelRegistry {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographTunnelRegistry.class);

    private final Map<Long, TunnelConnection> connections = new ConcurrentHashMap<>();

    /** Registers a newly handshaken tunnel, displacing any previous one for the same device. */
    public void register(TunnelConnection connection) {
        TunnelConnection previous = connections.put(connection.getDeviceId(), connection);
        if (previous != null && previous != connection) {
            LOGGER.info("Replacing existing tachograph tunnel for device {}", connection.getDeviceId());
            previous.close();
        }
        LOGGER.info("Tachograph tunnel open for device {} ({})",
                connection.getDeviceId(), connection.getUniqueId());
    }

    /** Removes a tunnel, but only if it is still the registered one for that device. */
    public void deregister(TunnelConnection connection) {
        if (connections.remove(connection.getDeviceId(), connection)) {
            LOGGER.info("Tachograph tunnel closed for device {} ({})",
                    connection.getDeviceId(), connection.getUniqueId());
        }
    }

    /** The open tunnel for a device, or null when the device has none. */
    public TunnelConnection get(long deviceId) {
        TunnelConnection connection = connections.get(deviceId);
        if (connection != null && !connection.isOpen()) {
            connections.remove(deviceId, connection);
            return null;
        }
        return connection;
    }

    public boolean isConnected(long deviceId) {
        return get(deviceId) != null;
    }

    public Collection<TunnelConnection> getAll() {
        return List.copyOf(connections.values());
    }

    public int size() {
        return connections.size();
    }
}
