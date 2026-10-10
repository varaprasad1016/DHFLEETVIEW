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
 * Raised when the vehicle unit violates the download protocol: bad framing, bad checksum,
 * an unexpected service identifier, or a negative response that cannot be retried.
 */
public class VuProtocolException extends Exception {

    private static final long serialVersionUID = 1L;

    private final int negativeResponseCode;

    public VuProtocolException(String message) {
        this(message, -1);
    }

    public VuProtocolException(String message, int negativeResponseCode) {
        super(message);
        this.negativeResponseCode = negativeResponseCode;
    }

    public VuProtocolException(String message, Throwable cause) {
        super(message, cause);
        this.negativeResponseCode = -1;
    }

    /** The KWP2000 negative response code that caused this failure, or -1 when not applicable. */
    public int getNegativeResponseCode() {
        return negativeResponseCode;
    }
}
