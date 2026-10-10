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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Transfer Response Parameter (TREP) identifiers used by the vehicle-unit data download protocol.
 *
 * <p>Defined by Commission Regulation (EEC) No 3821/85 Annex 1B Appendix 7 (generation 1) and
 * Commission Implementing Regulation (EU) 2016/799 Annex 1C Appendix 7 (generation 2 and
 * generation 2 version 2). Each TREP names one data block that the vehicle unit returns in
 * response to a {@code TransferData} request; concatenating the responses produces the DDD file.
 */
public enum TrepType {

    OVERVIEW(0x01, 1, "Overview", true),
    ACTIVITIES(0x02, 1, "Activities", true),
    EVENTS_FAULTS(0x03, 1, "EventsAndFaults", true),
    DETAILED_SPEED(0x04, 1, "DetailedSpeed", false),
    TECHNICAL_DATA(0x05, 1, "TechnicalData", true),
    CARD_DOWNLOAD(0x06, 1, "CardDownload", false),

    OVERVIEW_G2(0x21, 2, "OverviewG2", true),
    ACTIVITIES_G2(0x22, 2, "ActivitiesG2", true),
    EVENTS_FAULTS_G2(0x23, 2, "EventsAndFaultsG2", true),
    DETAILED_SPEED_G2(0x24, 2, "DetailedSpeedG2", false),
    TECHNICAL_DATA_G2(0x25, 2, "TechnicalDataG2", true),

    OVERVIEW_G2V2(0x31, 3, "OverviewG2V2", true),
    ACTIVITIES_G2V2(0x32, 3, "ActivitiesG2V2", true),
    EVENTS_FAULTS_G2V2(0x33, 3, "EventsAndFaultsG2V2", true),
    DETAILED_SPEED_G2V2(0x34, 3, "DetailedSpeedG2V2", false),
    TECHNICAL_DATA_G2V2(0x35, 3, "TechnicalDataG2V2", true);

    private static final Map<Integer, TrepType> BY_CODE = new LinkedHashMap<>();

    static {
        for (TrepType type : values()) {
            BY_CODE.put(type.code, type);
        }
    }

    private final int code;
    private final int generation;
    private final String label;
    private final boolean mandatory;

    TrepType(int code, int generation, String label, boolean mandatory) {
        this.code = code;
        this.generation = generation;
        this.label = label;
        this.mandatory = mandatory;
    }

    public int getCode() {
        return code;
    }

    /**
     * Vehicle-unit generation this TREP belongs to: 1 for Annex 1B, 2 for Annex 1C smart
     * tachographs, 3 for Annex 1C version 2 (smart tachograph 2).
     */
    public int getGeneration() {
        return generation;
    }

    public String getLabel() {
        return label;
    }

    /**
     * Whether a complete legal download must contain this block. Detailed speed is optional
     * because it is large and many operators exclude it; card download is request-specific.
     */
    public boolean isMandatory() {
        return mandatory;
    }

    public static TrepType fromCode(int code) {
        return BY_CODE.get(code & 0xFF);
    }

    /**
     * The ordered TREP sequence for a full vehicle-unit download of the given generation.
     *
     * @param generation      1, 2 or 3 as reported by the vehicle unit
     * @param includeSpeed    whether to request the detailed speed block
     */
    public static List<TrepType> vehicleSequence(int generation, boolean includeSpeed) {
        return switch (generation) {
            case 3 -> includeSpeed
                    ? List.of(OVERVIEW_G2V2, ACTIVITIES_G2V2, EVENTS_FAULTS_G2V2,
                            DETAILED_SPEED_G2V2, TECHNICAL_DATA_G2V2)
                    : List.of(OVERVIEW_G2V2, ACTIVITIES_G2V2, EVENTS_FAULTS_G2V2, TECHNICAL_DATA_G2V2);
            case 2 -> includeSpeed
                    ? List.of(OVERVIEW_G2, ACTIVITIES_G2, EVENTS_FAULTS_G2, DETAILED_SPEED_G2, TECHNICAL_DATA_G2)
                    : List.of(OVERVIEW_G2, ACTIVITIES_G2, EVENTS_FAULTS_G2, TECHNICAL_DATA_G2);
            default -> includeSpeed
                    ? List.of(OVERVIEW, ACTIVITIES, EVENTS_FAULTS, DETAILED_SPEED, TECHNICAL_DATA)
                    : List.of(OVERVIEW, ACTIVITIES, EVENTS_FAULTS, TECHNICAL_DATA);
        };
    }

    /**
     * The TREP sequence for downloading a driver card that is inserted in the vehicle unit.
     * Generation 2 vehicle units still use TREP 06 for the relayed card image.
     */
    public static List<TrepType> cardSequence(int generation) {
        return List.of(CARD_DOWNLOAD);
    }

    /**
     * Whether the request for this TREP carries a date range. Only the activities block is
     * date-bounded; every other block is returned in full.
     */
    public boolean isDateRanged() {
        return this == ACTIVITIES || this == ACTIVITIES_G2 || this == ACTIVITIES_G2V2;
    }
}
