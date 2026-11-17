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

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;

/**
 * Assembles the byte stream of a DDD file from the TREP blocks returned by a vehicle unit.
 *
 * <p>A DDD file is simply the concatenation of the {@code TransferData} positive-response data
 * fields, each beginning with {@code 0x76} followed by its TREP identifier. This builder appends
 * blocks in the order they were downloaded and records where each one landed so metadata can be
 * read back without re-parsing the whole file.
 */
public class DddFileBuilder {

    private final ByteArrayOutputStream output = new ByteArrayOutputStream();
    private final List<DddBlock> blocks = new ArrayList<>();

    /**
     * Appends one block's raw response bytes.
     *
     * @param trep the block identifier
     * @param day  the calendar day for date-ranged blocks, otherwise null
     * @param data the concatenated response data fields exactly as received
     */
    public void append(TrepType trep, Date day, byte[] data) {
        if (data == null || data.length == 0) {
            return;
        }
        int offset = output.size();
        output.write(data, 0, data.length);
        blocks.add(new DddBlock(trep, day, offset, data.length));
    }

    public boolean isEmpty() {
        return output.size() == 0;
    }

    public int size() {
        return output.size();
    }

    public byte[] toByteArray() {
        return output.toByteArray();
    }

    public List<DddBlock> getBlocks() {
        return Collections.unmodifiableList(blocks);
    }

    /** Whether at least one block of the given TREP was captured. */
    public boolean contains(TrepType trep) {
        return blocks.stream().anyMatch(block -> block.getTrep() == trep);
    }

    /** The first block of the given TREP, or null when it was not captured. */
    public DddBlock findFirst(TrepType trep) {
        return blocks.stream().filter(block -> block.getTrep() == trep).findFirst().orElse(null);
    }
}
