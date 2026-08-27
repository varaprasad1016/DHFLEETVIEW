/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.tachograph;

import java.util.Date;

/**
 * Result of a single FMC650 tachograph file transfer attempt.
 * In production this would be populated from the device's binary DDD payload.
 * For the simulator it is synthesised from a small fixture.
 */
public class TachographDownloadResult {

    private byte[] data;
    private String suggestedFileName;
    private String fileType;
    private Date downloadedAt;

    public TachographDownloadResult(byte[] data, String suggestedFileName, String fileType, Date downloadedAt) {
        this.data = data;
        this.suggestedFileName = suggestedFileName;
        this.fileType = fileType;
        this.downloadedAt = downloadedAt;
    }

    public byte[] getData() {
        return data;
    }

    public void setData(byte[] data) {
        this.data = data;
    }

    public String getSuggestedFileName() {
        return suggestedFileName;
    }

    public void setSuggestedFileName(String suggestedFileName) {
        this.suggestedFileName = suggestedFileName;
    }

    public String getFileType() {
        return fileType;
    }

    public void setFileType(String fileType) {
        this.fileType = fileType;
    }

    public Date getDownloadedAt() {
        return downloadedAt;
    }

    public void setDownloadedAt(Date downloadedAt) {
        this.downloadedAt = downloadedAt;
    }
}
