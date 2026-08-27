/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.schedule;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.TachographConfiguration;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.TachographManager;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.Date;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Polls tachograph configurations and creates automatic download jobs when
 * nextDriverDownload / nextVehicleDownload is due. Also retries jobs whose
 * nextRetryAt has elapsed.
 */
@Singleton
public class TaskTachographScheduler extends SingleScheduleTask {

    private static final Logger LOGGER = LoggerFactory.getLogger(TaskTachographScheduler.class);

    private final Config config;
    private final Storage storage;
    private final TachographManager tachographManager;

    @Inject
    public TaskTachographScheduler(Config config, Storage storage, TachographManager tachographManager) {
        this.config = config;
        this.storage = storage;
        this.tachographManager = tachographManager;
    }

    @Override
    public void schedule(ScheduledExecutorService executor) {
        // Every minute is frequent enough for daily intervals; no need for sub-minute precision.
        executor.scheduleAtFixedRate(this, 60, 60, TimeUnit.SECONDS);
    }

    @Override
    public void run() {
        if (!Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_ENABLED))) {
            return;
        }
        try {
            // Automatic downloads
            for (TachographConfiguration cfg : storage.getObjects(
                    TachographConfiguration.class, new Request(new Columns.All()))) {
                if (!cfg.getEnabled()) {
                    continue;
                }
                Date now = new Date();
                if (cfg.getDriverDownloadEnabled()
                        && cfg.getNextDriverDownload() != null
                        && !cfg.getNextDriverDownload().after(now)) {
                    try {
                        tachographManager.createDownloadJob(
                                cfg.getDeviceId(), "DRIVER", 0, null, null);
                        LOGGER.info("Auto-created DRIVER download job for device {}", cfg.getDeviceId());
                    } catch (Exception e) {
                        LOGGER.debug("Auto DRIVER job for device {} skipped: {}", cfg.getDeviceId(), e.getMessage());
                    }
                }
                if (cfg.getVehicleDownloadEnabled()
                        && cfg.getNextVehicleDownload() != null
                        && !cfg.getNextVehicleDownload().after(now)) {
                    try {
                        tachographManager.createDownloadJob(
                                cfg.getDeviceId(), "VEHICLE", 0, null, null);
                        LOGGER.info("Auto-created VEHICLE download job for device {}", cfg.getDeviceId());
                    } catch (Exception e) {
                        LOGGER.debug("Auto VEHICLE job for device {} skipped: {}", cfg.getDeviceId(), e.getMessage());
                    }
                }
            }

            // Retries
            try {
                tachographManager.processRetries();
            } catch (Exception e) {
                LOGGER.warn("Tachograph retry processing failed", e);
            }

        } catch (StorageException e) {
            LOGGER.warn("Tachograph scheduler error", e);
        }
    }
}
