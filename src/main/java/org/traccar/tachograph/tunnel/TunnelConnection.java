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

import io.netty.buffer.Unpooled;
import io.netty.channel.Channel;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.tachograph.protocol.VuChannel;

import java.io.IOException;
import java.util.Date;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * One live tachograph tunnel: a TCP connection that an FMC650 has opened to the server and that
 * the device bridges onto the tachograph's download interface.
 *
 * <p>Bytes arriving from the device are queued by the Netty event loop and drained by the
 * download worker thread through {@link #read}, which keeps protocol logic off the event loop.
 * A connection serves one download at a time; {@link #tryAcquire} enforces that.
 */
public class TunnelConnection implements VuChannel {

    private static final Logger LOGGER = LoggerFactory.getLogger(TunnelConnection.class);

    private final Channel channel;
    private final String uniqueId;
    private final long deviceId;
    private final Date connectedAt = new Date();

    private final BlockingQueue<byte[]> inbound = new LinkedBlockingQueue<>();
    private final AtomicBoolean leased = new AtomicBoolean();

    private volatile boolean closed;
    private volatile String failure;

    public TunnelConnection(Channel channel, String uniqueId, long deviceId) {
        this.channel = channel;
        this.uniqueId = uniqueId;
        this.deviceId = deviceId;
    }

    public String getUniqueId() {
        return uniqueId;
    }

    public long getDeviceId() {
        return deviceId;
    }

    public Date getConnectedAt() {
        return connectedAt;
    }

    public Channel getChannel() {
        return channel;
    }

    /** Whether a download currently holds this tunnel. */
    public boolean isLeased() {
        return leased.get();
    }

    /**
     * Takes exclusive use of the tunnel for one download.
     *
     * @return true when the caller now owns the tunnel, false when another download holds it
     */
    public boolean tryAcquire() {
        return leased.compareAndSet(false, true);
    }

    /** Releases the tunnel and discards any bytes left over from the finished download. */
    public void release() {
        inbound.clear();
        leased.set(false);
    }

    // -----------------------------------------------------------------------
    // Called from the Netty event loop
    // -----------------------------------------------------------------------

    void enqueue(byte[] data) {
        if (data.length > 0) {
            inbound.add(data);
        }
    }

    void markClosed(String reason) {
        closed = true;
        failure = reason;
        // Unblock a reader that is parked in poll().
        inbound.add(new byte[0]);
    }

    // -----------------------------------------------------------------------
    // VuChannel, called from the download worker thread
    // -----------------------------------------------------------------------

    @Override
    public void write(byte[] data) throws IOException {
        if (closed || !channel.isActive()) {
            throw new IOException("Tachograph tunnel to " + uniqueId + " is closed: " + describeFailure());
        }
        channel.writeAndFlush(Unpooled.wrappedBuffer(data));
    }

    @Override
    public byte[] read(long timeoutMillis) throws IOException {
        try {
            byte[] chunk = inbound.poll(Math.max(0, timeoutMillis), TimeUnit.MILLISECONDS);
            if (chunk == null) {
                if (closed) {
                    throw new IOException(
                            "Tachograph tunnel to " + uniqueId + " closed: " + describeFailure());
                }
                return new byte[0];
            }
            if (chunk.length == 0 && closed) {
                throw new IOException("Tachograph tunnel to " + uniqueId + " closed: " + describeFailure());
            }
            return chunk;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted while reading from tunnel to " + uniqueId, e);
        }
    }

    @Override
    public boolean isOpen() {
        return !closed && channel.isActive();
    }

    @Override
    public String getDescription() {
        return uniqueId;
    }

    @Override
    public void close() {
        if (channel.isActive()) {
            LOGGER.debug("Closing tachograph tunnel to {}", uniqueId);
            channel.close();
        }
        closed = true;
    }

    private String describeFailure() {
        return failure != null ? failure : "peer disconnected";
    }
}
