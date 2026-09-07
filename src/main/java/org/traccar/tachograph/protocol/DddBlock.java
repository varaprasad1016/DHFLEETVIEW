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

import java.util.Date;

/**
 * One TREP block inside an assembled DDD file, recorded with the offsets that
 * {@link DddFileBuilder} observed while writing it.
 *
 * <p>Keeping the boundaries alongside the bytes matters: a DDD file has no length prefixes, so
 * once the block structure is lost the only way to find a block again is to re-parse the whole
 * regulation data model. Recording offsets at assembly time makes metadata extraction reliable.
 */
public final class DddBlock {

    private final TrepType trep;
    private final Date day;
    private final int offset;
    private final int length;

    public DddBlock(TrepType trep, Date day, int offset, int length) {
        this.trep = trep;
        this.day = day;
        this.offset = offset;
        this.length = length;
    }

    public TrepType getTrep() {
        return trep;
    }

    /** For date-ranged blocks, the calendar day requested; null otherwise. */
    public Date getDay() {
        return day;
    }

    /** Offset of the block within the DDD file, including its {@code 0x76 TREP} prefix. */
    public int getOffset() {
        return offset;
    }

    public int getLength() {
        return length;
    }

    @Override
    public String toString() {
        return String.format("%s[%d bytes @ %d]", trep.getLabel(), length, offset);
    }
}
