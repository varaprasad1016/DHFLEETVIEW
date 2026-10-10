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
package org.traccar.tachograph.card;

/**
 * The answer a bridge returned for one {@link CardCommand}: either the card's response bytes or
 * a reason the reader could not produce them.
 */
public final class CardResponse {

    private final byte[] data;
    private final String errorCode;
    private final String errorMessage;

    private CardResponse(byte[] data, String errorCode, String errorMessage) {
        this.data = data;
        this.errorCode = errorCode;
        this.errorMessage = errorMessage;
    }

    public static CardResponse success(byte[] data) {
        return new CardResponse(data != null ? data : new byte[0], null, null);
    }

    public static CardResponse failure(String errorCode, String errorMessage) {
        return new CardResponse(null, errorCode, errorMessage);
    }

    public boolean isSuccess() {
        return errorCode == null;
    }

    public byte[] getData() {
        return data;
    }

    public String getErrorCode() {
        return errorCode;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    /**
     * The two-byte status word that closes every card response, or -1 when the response is too
     * short to contain one. {@code 0x9000} means success.
     */
    public int getStatusWord() {
        if (data == null || data.length < 2) {
            return -1;
        }
        return ((data[data.length - 2] & 0xFF) << 8) | (data[data.length - 1] & 0xFF);
    }
}
