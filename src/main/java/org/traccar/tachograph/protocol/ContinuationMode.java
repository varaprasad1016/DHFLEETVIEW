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
 * How a vehicle unit continues a data block that does not fit in one message.
 *
 * <p>A single message carries at most 255 data bytes, so every block larger than that arrives in
 * several. What the continuation messages look like is the one part of the download protocol
 * that manufacturers implement differently, and it decides whether the assembled DDD file is
 * byte-correct: get it wrong and the file gains or loses two bytes at every 255-byte boundary,
 * which no analysis bureau will parse.
 *
 * <p>Both observed behaviours are supported. {@link #REPEAT_HEADER} is the default because it is
 * what the vehicle units in the field have been seen to do; switch with
 * {@code tacho.vu.continuationMode} if a unit produces files an analysis bureau rejects. The
 * quickest way to tell them apart is to download a vehicle overview block, which is always
 * larger than one message, and check whether {@code 76 01} appears more than once in the result.
 */
public enum ContinuationMode {

    /**
     * Every message repeats the service identifier and the TREP byte. Those two bytes are
     * stripped from continuation messages when the file is assembled.
     */
    REPEAT_HEADER,

    /**
     * Only the first message carries the service identifier and TREP byte; continuation messages
     * are pure payload and are appended unchanged.
     */
    RAW_CONTINUATION;

    /** Parses a configured value, falling back to {@link #REPEAT_HEADER} for anything unknown. */
    public static ContinuationMode parse(String value) {
        if (value == null || value.isBlank()) {
            return REPEAT_HEADER;
        }
        try {
            return valueOf(value.trim().toUpperCase(java.util.Locale.ROOT));
        } catch (IllegalArgumentException e) {
            return REPEAT_HEADER;
        }
    }
}
