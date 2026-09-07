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
package org.traccar.schedule;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.TachographConfiguration;
import org.traccar.model.TachographDownloadJob;
import org.traccar.tachograph.TachographManager;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.Date;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Keeps scheduled downloads moving: creates jobs for vehicles whose next download is due, and
 * restarts jobs whose retry time has arrived.
 *
 * <p>Runs every minute. Download intervals are measured in days, so nothing here needs to be
 * prompt; what it must be is reliable, because a missed window is a compliance failure rather
 * than an inconvenience. A device that already has a job in flight is skipped rather than
 * queued twice.
 */
@Singleton
public class TaskTachographScheduler extends SingleScheduleTask {

    private static final Logger LOGGER = LoggerFactory.getLogger(TaskTachographScheduler.class);

    private static final long INTERVAL_SECONDS = 60;

    private final Config config;
    private final TachographManager tachographManager;

    @Inject
    public TaskTachographScheduler(Config config, TachographManager tachographManager) {
        this.config = config;
        this.tachographManager = tachographManager;
    }

    @Override
    public void schedule(ScheduledExecutorService executor) {
        executor.scheduleAtFixedRate(this, INTERVAL_SECONDS, INTERVAL_SECONDS, TimeUnit.SECONDS);
    }

    @Override
    public void run() {
        if (!config.getBoolean(Keys.TACHO_ENABLED)) {
            return;
        }
        try {
            createDueJobs();
        } catch (Exception e) {
            LOGGER.warn("Could not create scheduled tachograph downloads", e);
        }
        try {
            tachographManager.processRetries();
        } catch (Exception e) {
            LOGGER.warn("Could not process tachograph retries", e);
        }
    }

    private void createDueJobs() throws Exception {
        Date now = new Date();
        for (TachographConfiguration configuration : tachographManager.findDueConfigurations()) {

            if (configuration.getDriverDownloadEnabled()
                    && isDue(configuration.getNextDriverDownload(), now)) {
                queue(configuration.getDeviceId(), TachographDownloadJob.TYPE_DRIVER);
            }
            if (configuration.getVehicleDownloadEnabled()
                    && isDue(configuration.getNextVehicleDownload(), now)) {
                queue(configuration.getDeviceId(), TachographDownloadJob.TYPE_VEHICLE);
            }
        }
    }

    private boolean isDue(Date next, Date now) {
        return next == null || !next.after(now);
    }

    /**
     * Queues one scheduled download. A refusal here is normal rather than exceptional: the usual
     * reason is that the previous run for the same vehicle is still going, so it is logged at
     * debug and the next tick will try again.
     */
    private void queue(long deviceId, String downloadType) {
        try {
            tachographManager.createDownloadJob(deviceId, downloadType, 0, null, null);
            LOGGER.info("Scheduled a {} download for device {}", downloadType, deviceId);
        } catch (Exception e) {
            LOGGER.debug("Scheduled {} download for device {} not queued: {}",
                    downloadType, deviceId, e.getMessage());
        }
    }
}
