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
package org.traccar.tachograph.forward;

/**
 * A delivery to an analysis bureau failed.
 *
 * <p>The retryable flag is what stops the queue wasting a day of backoff on a problem no retry
 * can fix. A refused password or an unknown host key is permanent until somebody changes the
 * configuration; a connection reset is not.
 */
public class ForwardException extends Exception {

    private static final long serialVersionUID = 1L;

    public static final String ERROR_CONNECT = "TACHO_FORWARD_CONNECT";
    public static final String ERROR_AUTH = "TACHO_FORWARD_AUTH";
    public static final String ERROR_HOST_KEY = "TACHO_FORWARD_HOST_KEY";
    public static final String ERROR_TRANSFER = "TACHO_FORWARD_TRANSFER";
    public static final String ERROR_REJECTED = "TACHO_FORWARD_REJECTED";
    public static final String ERROR_CONFIGURATION = "TACHO_FORWARD_CONFIGURATION";

    private final String errorCode;
    private final boolean retryable;

    public ForwardException(String errorCode, String message, boolean retryable) {
        super(message);
        this.errorCode = errorCode;
        this.retryable = retryable;
    }

    public ForwardException(String errorCode, String message, boolean retryable, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode;
        this.retryable = retryable;
    }

    public String getErrorCode() {
        return errorCode;
    }

    /** Whether trying again later could succeed without anyone changing anything. */
    public boolean isRetryable() {
        return retryable;
    }
}
