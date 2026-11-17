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

import java.util.Date;

/**
 * Everything a {@link TachographDeviceClient} needs for one download attempt.
 *
 * <p>Passing a request object rather than a widening parameter list keeps the client contract
 * stable as the pipeline grows: the date range, the card session and progress reporting all
 * arrived after the first version of this interface.
 */
public class TachographDownloadRequest {

    /** Reports how far a download has got, so the operator sees movement on long transfers. */
    public interface ProgressListener {
        /**
         * @param percent zero to one hundred
         * @param detail  a short human-readable phase description, for example "Activities 12/28"
         */
        void onProgress(int percent, String detail);
    }

    private final long jobId;
    private final long deviceId;
    private final String downloadType;
    private Date from;
    private Date to;
    private String cardSessionToken;
    private ProgressListener progressListener = (percent, detail) -> { };

    public TachographDownloadRequest(long jobId, long deviceId, String downloadType) {
        this.jobId = jobId;
        this.deviceId = deviceId;
        this.downloadType = downloadType;
    }

    public long getJobId() {
        return jobId;
    }

    public long getDeviceId() {
        return deviceId;
    }

    public String getDownloadType() {
        return downloadType;
    }

    /** Start of the requested activity range, or null to use the configured default window. */
    public Date getFrom() {
        return from;
    }

    public TachographDownloadRequest setFrom(Date from) {
        this.from = from;
        return this;
    }

    /** End of the requested activity range, or null for today. */
    public Date getTo() {
        return to;
    }

    public TachographDownloadRequest setTo(Date to) {
        this.to = to;
        return this;
    }

    /**
     * Token of the open company-card session, or null when no card authentication is in play.
     */
    public String getCardSessionToken() {
        return cardSessionToken;
    }

    public TachographDownloadRequest setCardSessionToken(String cardSessionToken) {
        this.cardSessionToken = cardSessionToken;
        return this;
    }

    public ProgressListener getProgressListener() {
        return progressListener;
    }

    public TachographDownloadRequest setProgressListener(ProgressListener progressListener) {
        if (progressListener != null) {
            this.progressListener = progressListener;
        }
        return this;
    }
}
