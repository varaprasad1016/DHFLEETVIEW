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
package org.traccar.tachograph;

import org.traccar.tachograph.protocol.DddMetadata;

import java.util.Date;

/**
 * Result of one tachograph file transfer: the DDD bytes, a suggested file name and whatever the
 * file says about itself.
 */
public class TachographDownloadResult {

    private byte[] data;
    private String suggestedFileName;
    private String fileType;
    private Date downloadedAt;
    private DddMetadata metadata;
    private String clientType;

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

    /** Fields read out of the file, or null when it was not inspected. */
    public DddMetadata getMetadata() {
        return metadata;
    }

    public void setMetadata(DddMetadata metadata) {
        this.metadata = metadata;
    }

    /** Which client produced this file, for the audit trail. */
    public String getClientType() {
        return clientType;
    }

    public void setClientType(String clientType) {
        this.clientType = clientType;
    }
}
