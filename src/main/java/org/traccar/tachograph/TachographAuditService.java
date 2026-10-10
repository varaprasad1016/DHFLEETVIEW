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

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.model.TachographAudit;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Order;
import org.traccar.storage.query.Request;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.util.Date;
import java.util.List;

/**
 * Records who did what with tachograph data.
 *
 * <p>Writing an audit entry must never be able to fail an operation, so every failure here is
 * logged and swallowed: losing an audit line is bad, but failing a legally required download
 * because the audit table was briefly unavailable is worse.
 */
@Singleton
public class TachographAuditService {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographAuditService.class);

    /** Actor recorded for work the scheduler started rather than a person. */
    public static final String ACTOR_SCHEDULER = "scheduler";
    /** Actor recorded for work the server did on its own, such as a retry. */
    public static final String ACTOR_SYSTEM = "system";

    private static final int MAX_DETAIL_LENGTH = 1000;

    private final Storage storage;

    @Inject
    public TachographAuditService(Storage storage) {
        this.storage = storage;
    }

    /** Records an action taken by a logged-in user. */
    public void record(long userId, long deviceId, String action, String detail) {
        write(userId, deviceId, action, detail, null);
    }

    /** Records an action taken by the server itself. */
    public void recordSystem(long deviceId, String action, String detail, String actor) {
        write(0, deviceId, action, detail, actor != null ? actor : ACTOR_SYSTEM);
    }

    private void write(long userId, long deviceId, String action, String detail, String actor) {
        try {
            TachographAudit entry = new TachographAudit();
            entry.setUserId(userId);
            entry.setDeviceId(deviceId);
            entry.setAction(action);
            entry.setDetail(truncate(detail));
            entry.setActor(actor);
            entry.setCreatedAt(new Date());
            storage.addObject(entry, new Request(new Columns.Exclude("id")));
        } catch (StorageException e) {
            LOGGER.warn("Could not write the tachograph audit entry {} for device {}",
                    action, deviceId, e);
        }
    }

    /**
     * Reads the audit trail, newest first.
     *
     * @param deviceId restrict to one device, or null for all
     */
    public List<TachographAudit> list(Long deviceId, int limit) throws StorageException {
        int effectiveLimit = limit > 0 ? Math.min(limit, 1000) : 200;
        Request request = deviceId != null
                ? new Request(
                        new Columns.All(),
                        new Condition.Equals("deviceid", deviceId),
                        new Order("id", true, effectiveLimit))
                : new Request(new Columns.All(), null, new Order("id", true, effectiveLimit));
        return storage.getObjects(TachographAudit.class, request);
    }

    private String truncate(String detail) {
        if (detail == null) {
            return null;
        }
        return detail.length() <= MAX_DETAIL_LENGTH ? detail : detail.substring(0, MAX_DETAIL_LENGTH);
    }
}
