/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.schedule;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.tachograph.TachographManager;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * One-shot recovery that runs shortly after startup to retry or fail jobs
 * that were left in transient states when the server was stopped.
 */
@Singleton
public class TaskTachographRecovery extends SingleScheduleTask {

    private static final Logger LOGGER = LoggerFactory.getLogger(TaskTachographRecovery.class);

    private final TachographManager tachographManager;

    @Inject
    public TaskTachographRecovery(TachographManager tachographManager) {
        this.tachographManager = tachographManager;
    }

    @Override
    public void schedule(ScheduledExecutorService executor) {
        executor.schedule(this, 30, TimeUnit.SECONDS);
    }

    @Override
    public void run() {
        try {
            tachographManager.recoverStaleJobs();
        } catch (Exception e) {
            LOGGER.warn("Tachograph recovery failed", e);
        }
    }
}
