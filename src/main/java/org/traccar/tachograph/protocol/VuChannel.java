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

import java.io.IOException;

/**
 * A bidirectional byte channel that reaches a vehicle unit's download interface.
 *
 * <p>In production this is the TCP tunnel that an FMC650 opens to the server, which the
 * device bridges onto the tachograph's K-line. In tests it is backed by an in-memory
 * vehicle-unit emulator. The channel carries raw {@link VuMessage} frames in both
 * directions; framing and retry live in {@link VuDownloadSession}.
 */
public interface VuChannel extends AutoCloseable {

    /**
     * Writes bytes towards the vehicle unit. Implementations must write the whole buffer.
     */
    void write(byte[] data) throws IOException;

    /**
     * Reads whatever bytes are currently available, blocking up to {@code timeoutMillis}.
     *
     * @return the bytes read, or an empty array when the timeout elapsed with no data
     * @throws IOException when the channel has failed or been closed by the peer
     */
    byte[] read(long timeoutMillis) throws IOException;

    /** Whether the underlying transport is still usable. */
    boolean isOpen();

    /** A short human-readable identity used in logs, for example the device IMEI. */
    String getDescription();

    @Override
    void close();
}
