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

@StorageName("tc_tachograph_download_jobs")
public class TachographDownloadJob extends BaseModel {

    public static final String TYPE_DRIVER = "DRIVER";
    public static final String TYPE_VEHICLE = "VEHICLE";

    public static final String STATUS_QUEUED = "QUEUED";
    public static final String STATUS_WAITING_FOR_DEVICE = "WAITING_FOR_DEVICE";
    public static final String STATUS_WAITING_FOR_BRIDGE = "WAITING_FOR_BRIDGE";
    public static final String STATUS_REQUESTING = "REQUESTING";
    public static final String STATUS_DOWNLOADING = "DOWNLOADING";
    public static final String STATUS_PROCESSING = "PROCESSING";
    public static final String STATUS_COMPLETED = "COMPLETED";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_CANCELLED = "CANCELLED";

    public static final String ERROR_DEVICE_OFFLINE = "TACHO_DEVICE_OFFLINE";
    public static final String ERROR_DOWNLOAD_TIMEOUT = "TACHO_DOWNLOAD_TIMEOUT";
    public static final String ERROR_AUTHENTICATION_FAILED = "TACHO_AUTHENTICATION_FAILED";
    public static final String ERROR_CARD_UNAVAILABLE = "TACHO_CARD_UNAVAILABLE";
    public static final String ERROR_BRIDGE_UNAVAILABLE = "TACHO_BRIDGE_UNAVAILABLE";
    public static final String ERROR_PROTOCOL = "TACHO_PROTOCOL_ERROR";
    public static final String ERROR_INVALID_FILE = "TACHO_INVALID_FILE";
    public static final String ERROR_STORAGE = "TACHO_STORAGE_ERROR";
    public static final String ERROR_PERMISSION_DENIED = "TACHO_PERMISSION_DENIED";
    public static final String ERROR_ALREADY_RUNNING = "TACHO_ALREADY_RUNNING";
    public static final String ERROR_CARD_REMOVED = "TACHO_CARD_REMOVED";
    public static final String ERROR_CARD_LOCKED = "TACHO_CARD_LOCKED";
    public static final String ERROR_PROTOCOL_SPEC_MISSING = "TACHO_PROTOCOL_SPEC_MISSING";

    private long deviceId;
    private long requestedBy;
    private String downloadType;
    private Date requestedFrom;
    private Date requestedTo;
    private String status;
    private int progress;
    private int retryCount;
    private Date queuedAt;
    private Date startedAt;
    private Date completedAt;
    private Date failedAt;
    private Date nextRetryAt;
    private String errorCode;
    private String errorMessage;
    private long fileId;
    private Date createdAt;
    private Date updatedAt;

    private String progressDetail;
    private String clientType;
    private boolean cancelRequested;
    private long bridgeId;
    private Date attemptStartedAt;

    private String deviceName;

    private String requestedByName;

    public long getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(long deviceId) {
        this.deviceId = deviceId;
    }

    public long getRequestedBy() {
        return requestedBy;
    }

    public void setRequestedBy(long requestedBy) {
        this.requestedBy = requestedBy;
    }

    public String getDownloadType() {
        return downloadType;
    }

    public void setDownloadType(String downloadType) {
        this.downloadType = downloadType;
    }

    public Date getRequestedFrom() {
        return requestedFrom;
    }

    public void setRequestedFrom(Date requestedFrom) {
        this.requestedFrom = requestedFrom;
    }

    public Date getRequestedTo() {
        return requestedTo;
    }

    public void setRequestedTo(Date requestedTo) {
        this.requestedTo = requestedTo;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public int getProgress() {
        return progress;
    }

    public void setProgress(int progress) {
        this.progress = progress;
    }

    public int getRetryCount() {
        return retryCount;
    }

    public void setRetryCount(int retryCount) {
        this.retryCount = retryCount;
    }

    public Date getQueuedAt() {
        return queuedAt;
    }

    public void setQueuedAt(Date queuedAt) {
        this.queuedAt = queuedAt;
    }

    public Date getStartedAt() {
        return startedAt;
    }

    public void setStartedAt(Date startedAt) {
        this.startedAt = startedAt;
    }

    public Date getCompletedAt() {
        return completedAt;
    }

    public void setCompletedAt(Date completedAt) {
        this.completedAt = completedAt;
    }

    public Date getFailedAt() {
        return failedAt;
    }

    public void setFailedAt(Date failedAt) {
        this.failedAt = failedAt;
    }

    public Date getNextRetryAt() {
        return nextRetryAt;
    }

    public void setNextRetryAt(Date nextRetryAt) {
        this.nextRetryAt = nextRetryAt;
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

    public long getFileId() {
        return fileId;
    }

    public void setFileId(long fileId) {
        this.fileId = fileId;
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

    /** Short description of the current phase, for example "Activities, day 12 of 92". */
    public String getProgressDetail() {
        return progressDetail;
    }

    public void setProgressDetail(String progressDetail) {
        this.progressDetail = progressDetail;
    }

    /** Which device client ran the job: FMC650 or SIMULATED. */
    public String getClientType() {
        return clientType;
    }

    public void setClientType(String clientType) {
        this.clientType = clientType;
    }

    /**
     * Set when an operator asks to cancel. A running job checks this between data blocks and
     * stops at the next safe point rather than being killed mid-transfer.
     */
    public boolean getCancelRequested() {
        return cancelRequested;
    }

    public void setCancelRequested(boolean cancelRequested) {
        this.cancelRequested = cancelRequested;
    }

    /** The bridge whose company card authorised this download, or zero when none was needed. */
    public long getBridgeId() {
        return bridgeId;
    }

    public void setBridgeId(long bridgeId) {
        this.bridgeId = bridgeId;
    }

    /** When the current attempt began, as distinct from when the job was first started. */
    public Date getAttemptStartedAt() {
        return attemptStartedAt;
    }

    public void setAttemptStartedAt(Date attemptStartedAt) {
        this.attemptStartedAt = attemptStartedAt;
    }

    @QueryIgnore
    public String getDeviceName() {
        return deviceName;
    }

    public void setDeviceName(String deviceName) {
        this.deviceName = deviceName;
    }

    @QueryIgnore
    public String getRequestedByName() {
        return requestedByName;
    }

    public void setRequestedByName(String requestedByName) {
        this.requestedByName = requestedByName;
    }
}
