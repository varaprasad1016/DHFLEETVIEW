/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.tachograph;

/**
 * Exception with a stable error code for tachograph operations.
 */
public class TachographException extends Exception {

    public static final String DEVICE_OFFLINE = "TACHO_DEVICE_OFFLINE";
    public static final String DOWNLOAD_TIMEOUT = "TACHO_DOWNLOAD_TIMEOUT";
    public static final String AUTHENTICATION_FAILED = "TACHO_AUTHENTICATION_FAILED";
    public static final String CARD_UNAVAILABLE = "TACHO_CARD_UNAVAILABLE";
    public static final String BRIDGE_UNAVAILABLE = "TACHO_BRIDGE_UNAVAILABLE";
    public static final String PROTOCOL_ERROR = "TACHO_PROTOCOL_ERROR";
    public static final String INVALID_FILE = "TACHO_INVALID_FILE";
    public static final String STORAGE_ERROR = "TACHO_STORAGE_ERROR";
    public static final String PERMISSION_DENIED = "TACHO_PERMISSION_DENIED";
    public static final String ALREADY_RUNNING = "TACHO_ALREADY_RUNNING";
    public static final String CARD_REMOVED = "TACHO_CARD_REMOVED";
    public static final String CARD_LOCKED = "TACHO_CARD_LOCKED";
    public static final String PROTOCOL_SPEC_MISSING = "TACHO_PROTOCOL_SPEC_MISSING";

    private final String errorCode;

    public TachographException(String errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public TachographException(String errorCode, String message, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode;
    }

    public String getErrorCode() {
        return errorCode;
    }
}
