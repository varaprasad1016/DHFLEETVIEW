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

/**
 * An entry in the tachograph audit trail.
 *
 * <p>Driver hours data is personal data and its handling is regulated, so every request for it,
 * every delivery of it and every download of a stored file is recorded with who did it and when.
 */
@StorageName("tc_tachograph_audit")
public class TachographAudit extends BaseModel {

    public static final String ACTION_DOWNLOAD_REQUESTED = "DOWNLOAD_REQUESTED";
    public static final String ACTION_DOWNLOAD_COMPLETED = "DOWNLOAD_COMPLETED";
    public static final String ACTION_DOWNLOAD_FAILED = "DOWNLOAD_FAILED";
    public static final String ACTION_DOWNLOAD_CANCELLED = "DOWNLOAD_CANCELLED";
    public static final String ACTION_FILE_RETRIEVED = "FILE_RETRIEVED";
    public static final String ACTION_FILE_DELETED = "FILE_DELETED";
    public static final String ACTION_FORWARD_QUEUED = "FORWARD_QUEUED";
    public static final String ACTION_FORWARD_DELIVERED = "FORWARD_DELIVERED";
    public static final String ACTION_FORWARD_FAILED = "FORWARD_FAILED";
    public static final String ACTION_TARGET_CHANGED = "TARGET_CHANGED";
    public static final String ACTION_BRIDGE_PAIRED = "BRIDGE_PAIRED";
    public static final String ACTION_BRIDGE_REMOVED = "BRIDGE_REMOVED";
    public static final String ACTION_CARD_READ = "CARD_READ";
    public static final String ACTION_CONFIG_CHANGED = "CONFIG_CHANGED";

    private long userId;
    private long deviceId;
    private String action;
    private String detail;
    private String actor;
    private Date createdAt;

    private String userName;
    private String deviceName;

    public long getUserId() {
        return userId;
    }

    public void setUserId(long userId) {
        this.userId = userId;
    }

    public long getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(long deviceId) {
        this.deviceId = deviceId;
    }

    public String getAction() {
        return action;
    }

    public void setAction(String action) {
        this.action = action;
    }

    public String getDetail() {
        return detail;
    }

    public void setDetail(String detail) {
        this.detail = detail;
    }

    /** Who acted, when it was not a logged-in user: a scheduler, a bridge, or the system. */
    public String getActor() {
        return actor;
    }

    public void setActor(String actor) {
        this.actor = actor;
    }

    public Date getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Date createdAt) {
        this.createdAt = createdAt;
    }

    @QueryIgnore
    public String getUserName() {
        return userName;
    }

    public void setUserName(String userName) {
        this.userName = userName;
    }

    @QueryIgnore
    public String getDeviceName() {
        return deviceName;
    }

    public void setDeviceName(String deviceName) {
        this.deviceName = deviceName;
    }
}
