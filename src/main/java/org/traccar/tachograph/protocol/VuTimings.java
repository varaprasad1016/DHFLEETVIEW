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

/**
 * Timing parameters for the vehicle-unit download session.
 *
 * <p>The names follow the ISO 14230-2 convention used by Annex 1B Appendix 7. The defaults are
 * the regulation's extended-timing values, widened for the round trip through the mobile network
 * and the FMC650 tunnel — a K-line byte that would arrive in milliseconds on a bench harness can
 * take a second or more over GPRS.
 *
 * <p>{@link #getBlockIdleMillis()} is the one parameter that is deployment-tuned rather than
 * specified: it decides how long the server waits after the last sub-message of a TREP block
 * before concluding that the block is complete. Raise it if large blocks are truncated on real
 * hardware; lower it to speed up downloads on a fast link. See
 * {@code docs/tachograph/VU-PROTOCOL.md}.
 */
public final class VuTimings {

    private final long responseTimeoutMillis;
    private final long blockIdleMillis;
    private final long pendingExtensionMillis;
    private final long totalBlockTimeoutMillis;
    private final int maxRequestAttempts;

    private VuTimings(
            long responseTimeoutMillis, long blockIdleMillis, long pendingExtensionMillis,
            long totalBlockTimeoutMillis, int maxRequestAttempts) {
        this.responseTimeoutMillis = responseTimeoutMillis;
        this.blockIdleMillis = blockIdleMillis;
        this.pendingExtensionMillis = pendingExtensionMillis;
        this.totalBlockTimeoutMillis = totalBlockTimeoutMillis;
        this.maxRequestAttempts = maxRequestAttempts;
    }

    public static VuTimings defaults() {
        return new VuTimings(20_000L, 5_000L, 30_000L, 900_000L, 3);
    }

    public static VuTimings of(
            long responseTimeoutMillis, long blockIdleMillis, long pendingExtensionMillis,
            long totalBlockTimeoutMillis, int maxRequestAttempts) {
        return new VuTimings(
                responseTimeoutMillis, blockIdleMillis, pendingExtensionMillis,
                totalBlockTimeoutMillis, Math.max(1, maxRequestAttempts));
    }

    /** How long to wait for the first response frame after sending a request. */
    public long getResponseTimeoutMillis() {
        return responseTimeoutMillis;
    }

    /** Idle gap after which a multi-frame TREP block is considered complete. */
    public long getBlockIdleMillis() {
        return blockIdleMillis;
    }

    /** How long a {@code responsePending} negative response extends the response deadline. */
    public long getPendingExtensionMillis() {
        return pendingExtensionMillis;
    }

    /** Hard ceiling on the time spent collecting a single TREP block. */
    public long getTotalBlockTimeoutMillis() {
        return totalBlockTimeoutMillis;
    }

    /** How many times a request is repeated after a {@code busyRepeatRequest} response. */
    public int getMaxRequestAttempts() {
        return maxRequestAttempts;
    }
}
