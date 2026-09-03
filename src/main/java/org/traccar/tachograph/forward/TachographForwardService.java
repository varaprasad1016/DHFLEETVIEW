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
package org.traccar.tachograph.forward;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.Device;
import org.traccar.model.Group;
import org.traccar.model.TachographAudit;
import org.traccar.model.TachographFile;
import org.traccar.model.TachographForward;
import org.traccar.model.TachographForwardTarget;
import org.traccar.model.User;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Order;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.TachographAuditService;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Delivers completed DDD files to analysis bureaux and keeps the record of having done so.
 *
 * <p>Delivery is queued rather than done inline. A download that has succeeded is a legal record
 * the operator now holds, and it must not be lost because a bureau's SFTP server happened to be
 * down at that moment. Each file and target pair becomes a row that is retried on a widening
 * backoff until it is delivered or an unfixable rejection stops it.
 */
@Singleton
public class TachographForwardService {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographForwardService.class);

    /** Default retry backoff, used when the configured one cannot be parsed. */
    private static final int[] DEFAULT_RETRY_DELAYS = {60, 300, 1800, 7200, 21600};

    private final Config config;
    private final Storage storage;
    private final SecretCipher secretCipher;
    private final TachographAuditService auditService;
    private final Map<String, TachographForwarder> forwarders;

    @Inject
    public TachographForwardService(
            Config config,
            Storage storage,
            SecretCipher secretCipher,
            TachographAuditService auditService,
            SftpForwarder sftpForwarder,
            HttpsForwarder httpsForwarder) {
        this.config = config;
        this.storage = storage;
        this.secretCipher = secretCipher;
        this.auditService = auditService;
        this.forwarders = Map.of(
                sftpForwarder.getTransport(), sftpForwarder,
                httpsForwarder.getTransport(), httpsForwarder);
    }

    // -----------------------------------------------------------------------
    // Targets
    // -----------------------------------------------------------------------

    /** Targets in groups the user can see. An administrator sees every target. */
    public List<TachographForwardTarget> listTargets(long userId, boolean administrator)
            throws StorageException {

        List<TachographForwardTarget> targets = storage.getObjects(
                TachographForwardTarget.class, new Request(new Columns.All()));
        if (administrator) {
            return targets;
        }
        Set<Long> visibleGroups = accessibleGroupIds(userId);
        List<TachographForwardTarget> result = new ArrayList<>();
        for (TachographForwardTarget target : targets) {
            if (target.getGroupId() == 0 || visibleGroups.contains(target.getGroupId())) {
                result.add(target);
            }
        }
        return result;
    }

    public TachographForwardTarget getTarget(long targetId) throws StorageException {
        return storage.getObject(TachographForwardTarget.class,
                new Request(new Columns.All(), new Condition.Equals("id", targetId)));
    }

    /**
     * Creates or updates a target, encrypting any newly supplied credential.
     *
     * <p>A blank credential on an update leaves the stored one alone, so editing a target's
     * schedule does not silently wipe its password.
     */
    public TachographForwardTarget saveTarget(TachographForwardTarget target, long userId)
            throws StorageException {

        Date now = new Date();
        target.setUpdatedAt(now);

        String newSecret = target.getSecretInput();
        if (newSecret != null && !newSecret.isBlank()) {
            if (!secretCipher.isConfigured()) {
                throw new IllegalStateException(
                        "tacho.forward.secret must be set in the configuration file before a "
                                + "forwarding credential can be stored");
            }
            target.setSecret(secretCipher.encrypt(newSecret));
            target.setSecretInput(null);
        }

        if (target.getId() == 0) {
            target.setCreatedAt(now);
            if (target.getLastStatus() == null) {
                target.setLastStatus(TachographForwardTarget.STATUS_UNTESTED);
            }
            long id = storage.addObject(target, new Request(new Columns.Exclude("id")));
            target.setId(id);
            LOGGER.info("Created the tachograph forwarding target {}", target.getName());
        } else {
            TachographForwardTarget existing = getTarget(target.getId());
            if (existing != null && (newSecret == null || newSecret.isBlank())) {
                target.setSecret(existing.getSecret());
            }
            storage.updateObject(target,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", target.getId())));
            LOGGER.info("Updated the tachograph forwarding target {}", target.getName());
        }

        auditService.record(userId, 0, TachographAudit.ACTION_TARGET_CHANGED,
                "Target " + target.getName() + " saved");
        return target;
    }

    public void deleteTarget(long targetId, long userId) throws StorageException {
        TachographForwardTarget target = getTarget(targetId);
        if (target == null) {
            return;
        }
        // Cancel anything still waiting to go there, so the queue does not retry forever.
        for (TachographForward forward : storage.getObjects(TachographForward.class, new Request(
                new Columns.All(), new Condition.Equals("targetid", targetId)))) {
            if (TachographForward.STATUS_QUEUED.equals(forward.getStatus())) {
                forward.setStatus(TachographForward.STATUS_CANCELLED);
                forward.setErrorMessage("Target removed");
                forward.setUpdatedAt(new Date());
                storage.updateObject(forward,
                        new Request(new Columns.Exclude("id"), new Condition.Equals("id", forward.getId())));
            }
        }
        storage.removeObject(TachographForwardTarget.class,
                new Request(new Condition.Equals("id", targetId)));
        auditService.record(userId, 0, TachographAudit.ACTION_TARGET_CHANGED,
                "Target " + target.getName() + " deleted");
        LOGGER.info("Deleted the tachograph forwarding target {}", target.getName());
    }

    /** Checks a target is reachable and its credential works, and records the result on it. */
    public void testTarget(long targetId, long userId) throws StorageException, ForwardException {
        TachographForwardTarget target = getTarget(targetId);
        if (target == null) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION, "Target not found: " + targetId, false);
        }
        TachographForwarder forwarder = resolveForwarder(target);
        target.setLastAttemptAt(new Date());
        try {
            forwarder.test(target, credentialsFor(target));
            target.setLastStatus(TachographForwardTarget.STATUS_OK);
            target.setLastMessage("Connection succeeded");
            target.setLastSuccessAt(new Date());
        } catch (ForwardException e) {
            target.setLastStatus(TachographForwardTarget.STATUS_FAILED);
            target.setLastMessage(e.getMessage());
            storage.updateObject(target,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", targetId)));
            throw e;
        } finally {
            target.setUpdatedAt(new Date());
        }
        storage.updateObject(target,
                new Request(new Columns.Exclude("id"), new Condition.Equals("id", targetId)));
        auditService.record(userId, 0, TachographAudit.ACTION_TARGET_CHANGED,
                "Target " + target.getName() + " tested successfully");
    }

    // -----------------------------------------------------------------------
    // Queueing
    // -----------------------------------------------------------------------

    /**
     * Queues a newly stored file for every enabled target that wants files of its type.
     *
     * @return how many deliveries were queued
     */
    public int enqueue(TachographFile file, Device device) throws StorageException {
        if (!config.getBoolean(Keys.TACHO_FORWARD_ENABLED)) {
            return 0;
        }

        long groupId = device != null ? device.getGroupId() : 0;
        int queued = 0;
        Date now = new Date();

        for (TachographForwardTarget target : storage.getObjects(
                TachographForwardTarget.class, new Request(new Columns.All()))) {

            if (!target.getEnabled()) {
                continue;
            }
            if (target.getGroupId() != 0 && target.getGroupId() != groupId) {
                continue;
            }
            if (!target.accepts(file.getFileType())) {
                continue;
            }

            TachographForward forward = new TachographForward();
            forward.setFileId(file.getId());
            forward.setTargetId(target.getId());
            forward.setDeviceId(file.getDeviceId());
            forward.setStatus(TachographForward.STATUS_QUEUED);
            forward.setAttempts(0);
            forward.setRemoteName(buildRemoteName(target, file, device));
            forward.setQueuedAt(now);
            forward.setNextAttemptAt(now);
            forward.setCreatedAt(now);
            forward.setUpdatedAt(now);
            storage.addObject(forward, new Request(new Columns.Exclude("id")));
            queued++;
        }

        if (queued > 0) {
            auditService.recordSystem(file.getDeviceId(), TachographAudit.ACTION_FORWARD_QUEUED,
                    "File " + file.getFileName() + " queued for " + queued + " target(s)",
                    TachographAuditService.ACTOR_SYSTEM);
            LOGGER.info("Queued {} for delivery to {} target(s)", file.getFileName(), queued);
        }
        return queued;
    }

    /**
     * Delivers everything that is due. Called by the scheduler; each delivery is independent, so
     * one bureau being down does not hold up another.
     */
    public void processQueue() throws StorageException {
        if (!config.getBoolean(Keys.TACHO_FORWARD_ENABLED)) {
            return;
        }

        Date now = new Date();
        List<TachographForward> pending = storage.getObjects(TachographForward.class, new Request(
                new Columns.All(),
                new Condition.Equals("status", TachographForward.STATUS_QUEUED),
                new Order("id", false, 100)));

        for (TachographForward forward : pending) {
            if (forward.getNextAttemptAt() != null && forward.getNextAttemptAt().after(now)) {
                continue;
            }
            try {
                attemptDelivery(forward);
            } catch (Exception e) {
                LOGGER.warn("Delivery {} failed unexpectedly", forward.getId(), e);
            }
        }
    }

    private void attemptDelivery(TachographForward forward) throws StorageException {
        TachographForwardTarget target = getTarget(forward.getTargetId());
        TachographFile file = storage.getObject(TachographFile.class,
                new Request(new Columns.All(), new Condition.Equals("id", forward.getFileId())));

        if (target == null || file == null) {
            fail(forward, ForwardException.ERROR_CONFIGURATION,
                    target == null ? "Target no longer exists" : "File no longer exists", false);
            return;
        }
        if (!target.getEnabled()) {
            return;
        }

        Path localFile = Path.of(file.getStoragePath());
        if (!Files.exists(localFile)) {
            fail(forward, ForwardException.ERROR_CONFIGURATION,
                    "The stored file is missing from disk: " + file.getFileName(), false);
            return;
        }

        forward.setStatus(TachographForward.STATUS_SENDING);
        forward.setAttempts(forward.getAttempts() + 1);
        forward.setLastAttemptAt(new Date());
        forward.setUpdatedAt(new Date());
        storage.updateObject(forward,
                new Request(new Columns.Exclude("id"), new Condition.Equals("id", forward.getId())));

        try {
            TachographForwarder forwarder = resolveForwarder(target);
            forwarder.deliver(target, credentialsFor(target), localFile, forward.getRemoteName());

            Date now = new Date();
            forward.setStatus(TachographForward.STATUS_DELIVERED);
            forward.setCompletedAt(now);
            forward.setErrorCode(null);
            forward.setErrorMessage(null);
            forward.setNextAttemptAt(null);
            forward.setUpdatedAt(now);
            storage.updateObject(forward,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", forward.getId())));

            target.setLastStatus(TachographForwardTarget.STATUS_OK);
            target.setLastMessage("Delivered " + forward.getRemoteName());
            target.setLastSuccessAt(now);
            target.setLastAttemptAt(now);
            target.setUpdatedAt(now);
            storage.updateObject(target,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", target.getId())));

            auditService.recordSystem(forward.getDeviceId(), TachographAudit.ACTION_FORWARD_DELIVERED,
                    forward.getRemoteName() + " delivered to " + target.getName(),
                    TachographAuditService.ACTOR_SYSTEM);

        } catch (ForwardException e) {
            recordTargetFailure(target, e);
            fail(forward, e.getErrorCode(), e.getMessage(), e.isRetryable());
        }
    }

    /** Applies the outcome of a failed attempt: schedule a retry, or stop trying. */
    private void fail(TachographForward forward, String errorCode, String message, boolean retryable)
            throws StorageException {

        int maxAttempts = config.getInteger(Keys.TACHO_FORWARD_MAX_ATTEMPTS);
        int[] delays = parseRetryDelays(config.getString(Keys.TACHO_FORWARD_RETRY_DELAYS));
        Date now = new Date();

        forward.setErrorCode(errorCode);
        forward.setErrorMessage(message);
        forward.setUpdatedAt(now);

        if (!retryable || forward.getAttempts() >= maxAttempts) {
            forward.setStatus(TachographForward.STATUS_FAILED);
            forward.setNextAttemptAt(null);
            LOGGER.warn("Delivery {} failed permanently after {} attempt(s): {}",
                    forward.getId(), forward.getAttempts(), message);
            auditService.recordSystem(forward.getDeviceId(), TachographAudit.ACTION_FORWARD_FAILED,
                    message, TachographAuditService.ACTOR_SYSTEM);
        } else {
            int delaySeconds = delays[Math.min(forward.getAttempts() - 1, delays.length - 1)];
            forward.setStatus(TachographForward.STATUS_QUEUED);
            forward.setNextAttemptAt(new Date(now.getTime() + delaySeconds * 1000L));
            LOGGER.info("Delivery {} failed, retrying in {} s: {}",
                    forward.getId(), delaySeconds, message);
        }
        storage.updateObject(forward,
                new Request(new Columns.Exclude("id"), new Condition.Equals("id", forward.getId())));
    }

    private void recordTargetFailure(TachographForwardTarget target, ForwardException e) {
        try {
            Date now = new Date();
            target.setLastStatus(TachographForwardTarget.STATUS_FAILED);
            target.setLastMessage(e.getMessage());
            target.setLastAttemptAt(now);
            target.setUpdatedAt(now);
            storage.updateObject(target,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", target.getId())));
        } catch (StorageException storageException) {
            LOGGER.warn("Could not record the failure on target {}", target.getName(), storageException);
        }
    }

    // -----------------------------------------------------------------------
    // Delivery records
    // -----------------------------------------------------------------------

    public List<TachographForward> listForwards(Long fileId, String status, int limit)
            throws StorageException {

        int effectiveLimit = limit > 0 ? Math.min(limit, 500) : 100;
        Condition condition = null;
        if (fileId != null) {
            condition = new Condition.Equals("fileid", fileId);
        }
        if (status != null && !status.isBlank()) {
            Condition statusCondition = new Condition.Equals("status", status);
            condition = condition == null ? statusCondition : new Condition.And(condition, statusCondition);
        }
        return storage.getObjects(TachographForward.class,
                new Request(new Columns.All(), condition, new Order("id", true, effectiveLimit)));
    }

    /** Puts a failed delivery back in the queue for an immediate attempt. */
    public void retry(long forwardId, long userId) throws StorageException {
        TachographForward forward = storage.getObject(TachographForward.class,
                new Request(new Columns.All(), new Condition.Equals("id", forwardId)));
        if (forward == null || TachographForward.STATUS_DELIVERED.equals(forward.getStatus())) {
            return;
        }
        forward.setStatus(TachographForward.STATUS_QUEUED);
        forward.setAttempts(0);
        forward.setNextAttemptAt(new Date());
        forward.setErrorCode(null);
        forward.setErrorMessage(null);
        forward.setUpdatedAt(new Date());
        storage.updateObject(forward,
                new Request(new Columns.Exclude("id"), new Condition.Equals("id", forwardId)));
        auditService.record(userId, forward.getDeviceId(), TachographAudit.ACTION_FORWARD_QUEUED,
                "Delivery " + forwardId + " re-queued");
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private TachographForwarder resolveForwarder(TachographForwardTarget target)
            throws ForwardException {
        TachographForwarder forwarder = forwarders.get(target.getTransport());
        if (forwarder == null) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Unsupported transport: " + target.getTransport(), false);
        }
        return forwarder;
    }

    private ForwardCredentials credentialsFor(TachographForwardTarget target) throws ForwardException {
        try {
            return new ForwardCredentials(
                    target.getUsername(), secretCipher.decrypt(target.getSecret()));
        } catch (IllegalStateException e) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION, e.getMessage(), false, e);
        }
    }

    /**
     * Builds the remote file name from the target's pattern. Bureaux differ on what they want to
     * see in a name, and some match files to vehicles by name alone, so this is configurable
     * rather than fixed.
     */
    private String buildRemoteName(
            TachographForwardTarget target, TachographFile file, Device device) {

        String pattern = target.getFileNamePattern();
        if (pattern == null || pattern.isBlank()) {
            return file.getFileName();
        }

        String registration = file.getVehicleRegistration();
        if (registration == null || registration.isBlank()) {
            registration = device != null ? device.getName() : String.valueOf(file.getDeviceId());
        }

        String expanded = pattern
                .replace("{name}", nullSafe(file.getFileName()))
                .replace("{device}", device != null ? nullSafe(device.getName()) : String.valueOf(file.getDeviceId()))
                .replace("{registration}", nullSafe(registration))
                .replace("{vin}", nullSafe(file.getVehicleIdentification()))
                .replace("{card}", nullSafe(file.getCardNumber()))
                .replace("{type}", nullSafe(file.getFileType()).toLowerCase(Locale.ROOT))
                .replace("{timestamp}", String.format("%tY%<tm%<td%<tH%<tM%<tS",
                        file.getDownloadedAt() != null ? file.getDownloadedAt() : new Date()));

        // A remote name must never contain a path separator: a bureau's pattern is not a place
        // to be able to write outside the upload directory.
        return expanded.replaceAll("[/\\\\]", "_");
    }

    private String nullSafe(String value) {
        return value != null ? value : "";
    }

    private int[] parseRetryDelays(String value) {
        if (value == null || value.isBlank()) {
            return DEFAULT_RETRY_DELAYS;
        }
        String[] parts = value.split(",");
        int[] delays = new int[parts.length];
        for (int i = 0; i < parts.length; i++) {
            try {
                delays[i] = Integer.parseInt(parts[i].trim());
            } catch (NumberFormatException e) {
                delays[i] = DEFAULT_RETRY_DELAYS[Math.min(i, DEFAULT_RETRY_DELAYS.length - 1)];
            }
        }
        return delays.length > 0 ? delays : DEFAULT_RETRY_DELAYS;
    }

    private Set<Long> accessibleGroupIds(long userId) throws StorageException {
        Set<Long> ids = new HashSet<>();
        for (Group group : storage.getObjects(Group.class, new Request(
                new Columns.Include("id"),
                new Condition.Permission(User.class, userId, Group.class)))) {
            ids.add(group.getId());
        }
        return ids;
    }
}
