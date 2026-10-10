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
 * One delivery of one DDD file to one analysis bureau.
 *
 * <p>Each file and target pair gets its own row, so a file going to two bureaux can succeed at
 * one and be retried at the other independently. The row is the evidence that a legally required
 * file reached where it had to, which is the question an operator gets asked in an audit.
 */
@StorageName("tc_tachograph_forwards")
public class TachographForward extends BaseModel {

    public static final String STATUS_QUEUED = "QUEUED";
    public static final String STATUS_SENDING = "SENDING";
    public static final String STATUS_DELIVERED = "DELIVERED";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_CANCELLED = "CANCELLED";

    private long fileId;
    private long targetId;
    private long deviceId;
    private String status;
    private int attempts;
    private String remoteName;
    private String errorCode;
    private String errorMessage;
    private Date queuedAt;
    private Date nextAttemptAt;
    private Date lastAttemptAt;
    private Date completedAt;
    private Date createdAt;
    private Date updatedAt;

    private String targetName;
    private String fileName;
    private String deviceName;

    public long getFileId() {
        return fileId;
    }

    public void setFileId(long fileId) {
        this.fileId = fileId;
    }

    public long getTargetId() {
        return targetId;
    }

    public void setTargetId(long targetId) {
        this.targetId = targetId;
    }

    public long getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(long deviceId) {
        this.deviceId = deviceId;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public int getAttempts() {
        return attempts;
    }

    public void setAttempts(int attempts) {
        this.attempts = attempts;
    }

    /** The name the file was written under at the far end. */
    public String getRemoteName() {
        return remoteName;
    }

    public void setRemoteName(String remoteName) {
        this.remoteName = remoteName;
    }

    public String getErrorCode() {
        return errorCode;
    }

    public void setErrorCode(String errorCode) {
        this.errorCode = errorCode;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public void setErrorMessage(String errorMessage) {
        this.errorMessage = errorMessage;
    }

    public Date getQueuedAt() {
        return queuedAt;
    }

    public void setQueuedAt(Date queuedAt) {
        this.queuedAt = queuedAt;
    }

    public Date getNextAttemptAt() {
        return nextAttemptAt;
    }

    public void setNextAttemptAt(Date nextAttemptAt) {
        this.nextAttemptAt = nextAttemptAt;
    }

    public Date getLastAttemptAt() {
        return lastAttemptAt;
    }

    public void setLastAttemptAt(Date lastAttemptAt) {
        this.lastAttemptAt = lastAttemptAt;
    }

    public Date getCompletedAt() {
        return completedAt;
    }

    public void setCompletedAt(Date completedAt) {
        this.completedAt = completedAt;
    }

    public Date getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Date createdAt) {
        this.createdAt = createdAt;
    }

    public Date getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Date updatedAt) {
        this.updatedAt = updatedAt;
    }

    @QueryIgnore
    public String getTargetName() {
        return targetName;
    }

    public void setTargetName(String targetName) {
        this.targetName = targetName;
    }

    @QueryIgnore
    public String getFileName() {
        return fileName;
    }

    public void setFileName(String fileName) {
        this.fileName = fileName;
    }

    @QueryIgnore
    public String getDeviceName() {
        return deviceName;
    }

    public void setDeviceName(String deviceName) {
        this.deviceName = deviceName;
    }
}
