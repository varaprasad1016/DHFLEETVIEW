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
import org.traccar.tachograph.forward.TachographForwardService;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Delivers queued DDD files to analysis bureaux such as Convey Reporting.
 *
 * <p>Delivery is separated from downloading on purpose. A file that has been downloaded is
 * already a record the operator holds, and it must survive the bureau being unreachable; running
 * the queue on its own timer means a transfer failure delays delivery rather than losing it.
 */
@Singleton
public class TaskTachographForwarder extends SingleScheduleTask {

    private static final Logger LOGGER = LoggerFactory.getLogger(TaskTachographForwarder.class);

    private static final long INITIAL_DELAY_SECONDS = 45;
    private static final long INTERVAL_SECONDS = 60;

    private final Config config;
    private final TachographForwardService forwardService;

    @Inject
    public TaskTachographForwarder(Config config, TachographForwardService forwardService) {
        this.config = config;
        this.forwardService = forwardService;
    }

    @Override
    public void schedule(ScheduledExecutorService executor) {
        executor.scheduleAtFixedRate(
                this, INITIAL_DELAY_SECONDS, INTERVAL_SECONDS, TimeUnit.SECONDS);
    }

    @Override
    public void run() {
        if (!config.getBoolean(Keys.TACHO_ENABLED) || !config.getBoolean(Keys.TACHO_FORWARD_ENABLED)) {
            return;
        }
        try {
            forwardService.processQueue();
        } catch (Exception e) {
            LOGGER.warn("Could not process the tachograph delivery queue", e);
        }
    }
}
