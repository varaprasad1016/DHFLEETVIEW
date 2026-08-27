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
package org.traccar.model;

import java.util.Date;

import org.traccar.storage.QueryIgnore;
import org.traccar.storage.StorageName;

@StorageName("tc_tachograph_bridges")
public class TachographBridge extends BaseModel {

    public static final String STATUS_ONLINE = "ONLINE";
    public static final String STATUS_OFFLINE = "OFFLINE";

    public static final String READER_NO_READER = "NO_READER";
    public static final String READER_CONNECTED = "READER_CONNECTED";
    public static final String READER_NO_CARD = "NO_CARD";
    public static final String READER_CARD_INSERTED = "CARD_INSERTED";
    public static final String READER_CARD_READING = "CARD_READING";
    public static final String READER_CARD_READY = "CARD_READY";
    public static final String READER_CARD_ERROR = "CARD_ERROR";
    public static final String READER_CARD_REMOVED = "CARD_REMOVED";

    private String bridgeId;
    private long groupId;
    private String name;
    private String status;
    private String tokenHash;
    private String readerStatus;
    private String cardStatus;
    private String cardIdentifier;
    private String cardType;
    private Date cardValidityTo;
    private String softwareVersion;
    private Date lastHeartbeat;
    private Date registeredAt;
    private Date lastSeenAt;
    private String pairingCodeHash;
    private Date pairingCodeExpiresAt;

    private String groupName;

    public String getBridgeId() {
        return bridgeId;
    }

    public void setBridgeId(String bridgeId) {
        this.bridgeId = bridgeId;
    }

    public long getGroupId() {
        return groupId;
    }

    public void setGroupId(long groupId) {
        this.groupId = groupId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getTokenHash() {
        return tokenHash;
    }

    public void setTokenHash(String tokenHash) {
        this.tokenHash = tokenHash;
    }

    public String getReaderStatus() {
        return readerStatus;
    }

    public void setReaderStatus(String readerStatus) {
        this.readerStatus = readerStatus;
    }

    public String getCardStatus() {
        return cardStatus;
    }

    public void setCardStatus(String cardStatus) {
        this.cardStatus = cardStatus;
    }

    public String getCardIdentifier() {
        return cardIdentifier;
    }

    public void setCardIdentifier(String cardIdentifier) {
        this.cardIdentifier = cardIdentifier;
    }

    public String getCardType() {
        return cardType;
    }

    public void setCardType(String cardType) {
        this.cardType = cardType;
    }

    public Date getCardValidityTo() {
        return cardValidityTo;
    }

    public void setCardValidityTo(Date cardValidityTo) {
        this.cardValidityTo = cardValidityTo;
    }

    public String getSoftwareVersion() {
        return softwareVersion;
    }

    public void setSoftwareVersion(String softwareVersion) {
        this.softwareVersion = softwareVersion;
    }

    public Date getLastHeartbeat() {
        return lastHeartbeat;
    }

    public void setLastHeartbeat(Date lastHeartbeat) {
        this.lastHeartbeat = lastHeartbeat;
    }

    public Date getRegisteredAt() {
        return registeredAt;
    }

    public void setRegisteredAt(Date registeredAt) {
        this.registeredAt = registeredAt;
    }

    public Date getLastSeenAt() {
        return lastSeenAt;
    }

    public void setLastSeenAt(Date lastSeenAt) {
        this.lastSeenAt = lastSeenAt;
    }

    public String getPairingCodeHash() {
        return pairingCodeHash;
    }

    public void setPairingCodeHash(String pairingCodeHash) {
        this.pairingCodeHash = pairingCodeHash;
    }

    public Date getPairingCodeExpiresAt() {
        return pairingCodeExpiresAt;
    }

    public void setPairingCodeExpiresAt(Date pairingCodeExpiresAt) {
        this.pairingCodeExpiresAt = pairingCodeExpiresAt;
    }

    @QueryIgnore
    public String getGroupName() {
        return groupName;
    }

    public void setGroupName(String groupName) {
        this.groupName = groupName;
    }
}
