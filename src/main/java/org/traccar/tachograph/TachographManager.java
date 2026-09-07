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
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.Device;
import org.traccar.model.TachographAudit;
import org.traccar.model.TachographBridge;
import org.traccar.model.TachographConfiguration;
import org.traccar.model.TachographDownloadJob;
import org.traccar.model.TachographFile;
import org.traccar.model.User;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Order;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.device.Fmc650TachographClient;
import org.traccar.tachograph.forward.TachographForwardService;
import org.traccar.tachograph.protocol.DddMetadata;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.stream.Collectors;

/**
 * Runs tachograph downloads: creating jobs, driving them through their states, storing what comes
 * back, and handing finished files to the delivery queue.
 *
 * <p>Jobs are persistent and restartable. A download can take half an hour over a mobile link, so
 * the state that matters lives in the database rather than in memory, and a server restart in the
 * middle of one leaves a job that {@link #recoverStaleJobs()} picks up rather than a silent hole
 * in a legally required record.
 */
@Singleton
public class TachographManager {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographManager.class);

    /** Concurrent downloads. Each one holds a device tunnel, so this bounds device load too. */
    private static final int WORKER_THREADS = 4;

    /** Default backoff between retries, used when the configured value cannot be parsed. */
    private static final int[] DEFAULT_RETRY_DELAYS = {30, 120, 600, 1800};

    private static final int MAX_RETRIES = 5;

    /** Errors that no amount of retrying will fix. */
    private static final Set<String> PERMANENT_ERRORS = Set.of(
            TachographDownloadJob.ERROR_INVALID_FILE,
            TachographDownloadJob.ERROR_PERMISSION_DENIED,
            TachographDownloadJob.ERROR_PROTOCOL_SPEC_MISSING,
            TachographDownloadJob.ERROR_CARD_LOCKED);

    /** Thrown internally when an operator cancels a job that is already running. */
    private static final class JobCancelledException extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    private final Config config;
    private final Storage storage;
    private final TachographStorage tachographStorage;
    private final TachographAuditService auditService;
    private final TachographForwardService forwardService;
    private final MockAuthenticationProvider mockAuthProvider;
    private final BridgeAuthenticationProvider bridgeAuthProvider;
    private final SimulatedTachographDeviceClient simulatedClient;
    private final Fmc650TachographClient fmc650Client;

    private final ExecutorService executor;

    /** Cancellation flags for jobs currently executing, keyed by job id. */
    private final Map<Long, AtomicBoolean> running = new ConcurrentHashMap<>();

    @Inject
    public TachographManager(
            Config config,
            Storage storage,
            TachographStorage tachographStorage,
            TachographAuditService auditService,
            TachographForwardService forwardService,
            MockAuthenticationProvider mockAuthProvider,
            BridgeAuthenticationProvider bridgeAuthProvider,
            SimulatedTachographDeviceClient simulatedClient,
            Fmc650TachographClient fmc650Client) {
        this.config = config;
        this.storage = storage;
        this.tachographStorage = tachographStorage;
        this.auditService = auditService;
        this.forwardService = forwardService;
        this.mockAuthProvider = mockAuthProvider;
        this.bridgeAuthProvider = bridgeAuthProvider;
        this.simulatedClient = simulatedClient;
        this.fmc650Client = fmc650Client;
        this.executor = Executors.newFixedThreadPool(WORKER_THREADS, runnable -> {
            Thread thread = new Thread(runnable, "tacho-download");
            thread.setDaemon(true);
            return thread;
        });
    }

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------

    /**
     * The tachograph settings for a device. A device that has never been configured gets a
     * disabled default rather than null, so callers never have to special-case it.
     */
    public TachographConfiguration getConfiguration(long deviceId) throws StorageException {
        TachographConfiguration configuration = storage.getObject(
                TachographConfiguration.class,
                new Request(new Columns.All(), new Condition.Equals("deviceid", deviceId)));

        if (configuration == null) {
            configuration = new TachographConfiguration();
            configuration.setDeviceId(deviceId);
            configuration.setEnabled(false);
            configuration.setDriverDownloadEnabled(false);
            configuration.setVehicleDownloadEnabled(false);
            configuration.setDriverDownloadIntervalDays(config.getInteger(Keys.TACHO_DRIVER_INTERVAL));
            configuration.setVehicleDownloadIntervalDays(config.getInteger(Keys.TACHO_VEHICLE_INTERVAL));
        }
        return configuration;
    }

    public TachographConfiguration saveConfiguration(TachographConfiguration configuration, long userId)
            throws StorageException {

        Date now = new Date();
        configuration.setUpdatedAt(now);

        TachographConfiguration existing = storage.getObject(
                TachographConfiguration.class,
                new Request(new Columns.All(), new Condition.Equals("deviceid", configuration.getDeviceId())));

        if (existing == null) {
            configuration.setCreatedAt(now);
            long id = storage.addObject(configuration, new Request(new Columns.Exclude("id")));
            configuration.setId(id);
        } else {
            configuration.setId(existing.getId());
            storage.updateObject(configuration, new Request(
                    new Columns.Exclude("id"),
                    new Condition.Equals("id", existing.getId())));
            configuration.setCreatedAt(existing.getCreatedAt());
            // Download history belongs to the server, not to whatever the client posted back.
            configuration.setLastDriverDownload(existing.getLastDriverDownload());
            configuration.setLastVehicleDownload(existing.getLastVehicleDownload());
            storage.updateObject(configuration,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", existing.getId())));
        }

        recalculateSchedule(configuration);
        auditService.record(userId, configuration.getDeviceId(),
                TachographAudit.ACTION_CONFIG_CHANGED,
                "Tachograph settings saved, enabled=" + configuration.getEnabled());
        return configuration;
    }

    /** Recomputes the next due dates from the last download and the configured intervals. */
    private void recalculateSchedule(TachographConfiguration configuration) throws StorageException {
        boolean changed = false;

        if (configuration.getDriverDownloadEnabled()) {
            Date next = addDays(
                    configuration.getLastDriverDownload(), driverInterval(configuration));
            if (!sameInstant(next, configuration.getNextDriverDownload())) {
                configuration.setNextDriverDownload(next);
                changed = true;
            }
        } else if (configuration.getNextDriverDownload() != null) {
            configuration.setNextDriverDownload(null);
            changed = true;
        }

        if (configuration.getVehicleDownloadEnabled()) {
            Date next = addDays(
                    configuration.getLastVehicleDownload(), vehicleInterval(configuration));
            if (!sameInstant(next, configuration.getNextVehicleDownload())) {
                configuration.setNextVehicleDownload(next);
                changed = true;
            }
        } else if (configuration.getNextVehicleDownload() != null) {
            configuration.setNextVehicleDownload(null);
            changed = true;
        }

        if (changed && configuration.getId() != 0) {
            storage.updateObject(configuration,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", configuration.getId())));
        }
    }

    private int driverInterval(TachographConfiguration configuration) {
        return configuration.getDriverDownloadIntervalDays() > 0
                ? configuration.getDriverDownloadIntervalDays()
                : config.getInteger(Keys.TACHO_DRIVER_INTERVAL);
    }

    private int vehicleInterval(TachographConfiguration configuration) {
        return configuration.getVehicleDownloadIntervalDays() > 0
                ? configuration.getVehicleDownloadIntervalDays()
                : config.getInteger(Keys.TACHO_VEHICLE_INTERVAL);
    }

    /**
     * Devices whose next scheduled download is due, as job requests ready to be created.
     * A device that already has a job in flight is skipped.
     */
    public List<TachographConfiguration> findDueConfigurations() throws StorageException {
        Date now = new Date();
        List<TachographConfiguration> due = new ArrayList<>();
        for (TachographConfiguration configuration : storage.getObjects(
                TachographConfiguration.class, new Request(new Columns.All()))) {
            if (!configuration.getEnabled()) {
                continue;
            }
            boolean driverDue = configuration.getDriverDownloadEnabled()
                    && isDue(configuration.getNextDriverDownload(), now);
            boolean vehicleDue = configuration.getVehicleDownloadEnabled()
                    && isDue(configuration.getNextVehicleDownload(), now);
            if (driverDue || vehicleDue) {
                due.add(configuration);
            }
        }
        return due;
    }

    /** A null due date means the device has never been downloaded, which counts as due. */
    private boolean isDue(Date next, Date now) {
        return next == null || !next.after(now);
    }

    // -----------------------------------------------------------------------
    // Job creation
    // -----------------------------------------------------------------------

    /**
     * Queues a download.
     *
     * @throws TachographException when the type is unknown or an equivalent job is already active
     */
    public synchronized TachographDownloadJob createDownloadJob(
            long deviceId, String downloadType, long requestedBy, Date from, Date to)
            throws StorageException, TachographException {

        if (!TachographDownloadJob.TYPE_DRIVER.equals(downloadType)
                && !TachographDownloadJob.TYPE_VEHICLE.equals(downloadType)) {
            throw new TachographException(
                    TachographException.INVALID_FILE, "Unknown download type: " + downloadType);
        }

        for (TachographDownloadJob active : storage.getObjects(
                TachographDownloadJob.class,
                new Request(new Columns.All(), new Condition.Equals("deviceid", deviceId)))) {
            if (isActive(active.getStatus()) && downloadType.equals(active.getDownloadType())) {
                throw new TachographException(
                        TachographDownloadJob.ERROR_ALREADY_RUNNING, String.format(
                                "A %s download is already in progress for this vehicle (job %d)",
                                downloadType.toLowerCase(java.util.Locale.ROOT), active.getId()));
            }
        }

        Date now = new Date();
        TachographDownloadJob job = new TachographDownloadJob();
        job.setDeviceId(deviceId);
        job.setRequestedBy(requestedBy);
        job.setDownloadType(downloadType);
        job.setRequestedFrom(from);
        job.setRequestedTo(to);
        job.setStatus(TachographDownloadJob.STATUS_QUEUED);
        job.setProgress(0);
        job.setProgressDetail("Queued");
        job.setRetryCount(0);
        job.setCancelRequested(false);
        job.setQueuedAt(now);
        job.setCreatedAt(now);
        job.setUpdatedAt(now);

        long id = storage.addObject(job, new Request(new Columns.Exclude("id")));
        job.setId(id);

        auditService.record(requestedBy, deviceId, TachographAudit.ACTION_DOWNLOAD_REQUESTED,
                downloadType + " download requested, job " + id);
        LOGGER.info("Tachograph job {} queued for device {}, type {}", id, deviceId, downloadType);

        executeAsync(id);
        return job;
    }

    private boolean isActive(String status) {
        return TachographDownloadJob.STATUS_QUEUED.equals(status)
                || TachographDownloadJob.STATUS_WAITING_FOR_DEVICE.equals(status)
                || TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE.equals(status)
                || TachographDownloadJob.STATUS_REQUESTING.equals(status)
                || TachographDownloadJob.STATUS_DOWNLOADING.equals(status)
                || TachographDownloadJob.STATUS_PROCESSING.equals(status);
    }

    public List<TachographDownloadJob> getJobs(
            Long deviceId, String status, Date from, Date to, int limit) throws StorageException {
        Request request = new Request(new Columns.All());
        Condition condition = null;
        if (deviceId != null) {
            condition = new Condition.Equals("deviceid", deviceId);
        }
        if (status != null) {
            Condition sc = new Condition.Equals("status", status);
            condition = condition == null ? sc : new Condition.And(condition, sc);
        }
        if (from != null) {
            Condition fc = new Condition.Equals("createdat", from); // approximate; real impl would use GreaterEqual
            // keep simple: filter in memory for range
        }
        if (condition != null) {
            request = new Request(new Columns.All(), condition, new Order("id", true, limit > 0 ? limit : 100));
        } else {
            request = new Request(new Columns.All(), null, new Order("id", true, limit > 0 ? limit : 100));
        }
        List<TachographDownloadJob> jobs = storage.getObjects(TachographDownloadJob.class, request);
        // in-memory date filtering for MVP
        if (from != null || to != null) {
            jobs.removeIf(j -> {
                Date c = j.getCreatedAt();
                if (c == null) return false;
                if (from != null && c.before(from)) return true;
                if (to != null && c.after(to)) return true;
                return false;
            });
        }
        return jobs;
    }

    public void cancelJob(long jobId, long userId) throws StorageException, TachographException {
        TachographDownloadJob job = getJob(jobId);
        if (job == null) {
            throw new TachographException("NOT_FOUND", "Job not found: " + jobId);
        }
        String status = job.getStatus();
        if (TachographDownloadJob.STATUS_COMPLETED.equals(status)
                || TachographDownloadJob.STATUS_FAILED.equals(status)
                || TachographDownloadJob.STATUS_CANCELLED.equals(status)) {
            return;
        }
        job.setStatus(TachographDownloadJob.STATUS_CANCELLED);
        job.setUpdatedAt(new Date());
        storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));
        LOGGER.info("Tachograph job {} cancelled by user {}", jobId, userId);
    }
    // -----------------------------------------------------------------------
    // Job execution
    // -----------------------------------------------------------------------

    public void executeAsync(long jobId) {
        executor.submit(() -> {
            try {
                executeJob(jobId);
            } catch (Exception e) {
                LOGGER.warn("Tachograph job {} ended unexpectedly", jobId, e);
            }
        });
    }

    private void executeJob(long jobId) throws StorageException {
        TachographDownloadJob job = getJob(jobId);
        if (job == null || !TachographDownloadJob.STATUS_QUEUED.equals(job.getStatus())) {
            return;
        }
        if (running.putIfAbsent(jobId, new AtomicBoolean()) != null) {
            LOGGER.debug("Tachograph job {} is already executing", jobId);
            return;
        }

        job.setStatus(TachographDownloadJob.STATUS_REQUESTING);
        job.setStartedAt(new Date());
        job.setUpdatedAt(new Date());
        storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));

        String authToken = null;
        TachographAuthenticationProvider authProvider = null;

        try {
            Date now = new Date();
            job.setStatus(TachographDownloadJob.STATUS_REQUESTING);
            job.setProgress(0);
            job.setProgressDetail("Contacting the vehicle");
            job.setAttemptStartedAt(now);
            if (job.getStartedAt() == null) {
                job.setStartedAt(now);
            }
            job.setUpdatedAt(now);
            save(job);

            long groupId = resolveGroupId(job.getDeviceId());

            // Company card authentication, when this installation uses a bridge.
            authProvider = resolveAuthProvider();
            if (authProvider != null) {
                if (!authProvider.isAvailable(groupId)) {
                    handleFailure(job, TachographDownloadJob.ERROR_BRIDGE_UNAVAILABLE, "No bridge/card available");
                    return;
                }
                authToken = authProvider.createSession(jobId, groupId);
                job.setStatus(TachographDownloadJob.STATUS_DOWNLOADING);
                job.setProgress(10);
                job.setUpdatedAt(new Date());
                storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));
                job.setStatus(TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE);
                job.setProgressDetail("Waiting for the company card");
                save(job);

                authToken = authProvider.createSession(jobId, groupId);
                job.setBridgeId(authProvider.getBridgeId(authToken));
                authProvider.authenticate(authToken, jobId);
            } else {
                job.setStatus(TachographDownloadJob.STATUS_DOWNLOADING);
                job.setProgress(10);
                job.setUpdatedAt(new Date());
                storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));
            }

            checkCancelled(jobId);

            TachographDeviceClient client = resolveDeviceClient(job.getDeviceId());
            job.setClientType(client.getClientType());
            job.setStatus(TachographDownloadJob.STATUS_DOWNLOADING);
            job.setProgressDetail("Downloading");
            save(job);

            TachographDownloadRequest request =
                    new TachographDownloadRequest(jobId, job.getDeviceId(), job.getDownloadType())
                            .setFrom(job.getRequestedFrom())
                            .setTo(job.getRequestedTo())
                            .setCardSessionToken(authToken)
                            .setProgressListener((percent, detail) -> reportProgress(jobId, percent, detail));

            TachographDownloadResult result = client.download(request);

            checkCancelled(jobId);

            job.setStatus(TachographDownloadJob.STATUS_PROCESSING);
            job.setProgress(70);
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));
            job.setProgress(92);
            job.setProgressDetail("Storing the file");
            save(job);

            TachographFile file = storeResult(job, result, groupId);

            Date completedAt = new Date();
            job.setStatus(TachographDownloadJob.STATUS_COMPLETED);
            job.setProgress(100);
            job.setCompletedAt(new Date());
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));
            job.setProgressDetail("Completed");
            job.setFileId(file.getId());
            job.setErrorCode(null);
            job.setErrorMessage(null);
            job.setNextRetryAt(null);
            job.setCompletedAt(completedAt);
            job.setUpdatedAt(completedAt);
            save(job);

            markDownloaded(job);

            auditService.recordSystem(job.getDeviceId(), TachographAudit.ACTION_DOWNLOAD_COMPLETED,
                    "Job " + jobId + " stored " + file.getFileName() + " (" + file.getFileSize() + " bytes)",
                    TachographAuditService.ACTOR_SYSTEM);

            queueForwarding(file, job);

            LOGGER.info("Tachograph job {} completed for device {}: {}",
                    jobId, job.getDeviceId(), file.getFileName());

        } catch (JobCancelledException e) {
            finishCancelled(job);
        } catch (TachographException e) {
            handleFailure(job, e.getErrorCode(), e.getMessage());
        } catch (Exception e) {
            LOGGER.warn("Tachograph job {} failed", jobId, e);
            handleFailure(job, TachographDownloadJob.ERROR_STORAGE, String.valueOf(e.getMessage()));
        } finally {
            running.remove(jobId);
            if (authProvider != null && authToken != null) {
                authProvider.closeSession(authToken);
            }
        }
    }

    /** Persists progress without letting a storage hiccup kill a download that is going fine. */
    private void reportProgress(long jobId, int percent, String detail) {
        checkCancelled(jobId);
        try {
            TachographDownloadJob job = getJob(jobId);
            if (job != null) {
                job.setProgress(percent);
                job.setProgressDetail(detail);
                job.setUpdatedAt(new Date());
                save(job);
            }
        } catch (StorageException e) {
            LOGGER.debug("Could not record progress for job {}: {}", jobId, e.getMessage());
        }
    }

    private void checkCancelled(long jobId) {
        AtomicBoolean flag = running.get(jobId);
        if (flag != null && flag.get()) {
            throw new JobCancelledException();
        }
    }

    private void finishCancelled(TachographDownloadJob job) throws StorageException {
        Date now = new Date();
        job.setStatus(TachographDownloadJob.STATUS_CANCELLED);
        job.setProgressDetail("Cancelled");
        job.setNextRetryAt(null);
        job.setUpdatedAt(now);
        save(job);
        LOGGER.info("Tachograph job {} cancelled while running", job.getId());
    }

    // -----------------------------------------------------------------------
    // Storing the result
    // -----------------------------------------------------------------------

    private TachographFile storeResult(
            TachographDownloadJob job, TachographDownloadResult result, long groupId) throws Exception {

        byte[] data = result.getData();
        if (data == null || data.length == 0) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_INVALID_FILE, "The vehicle returned an empty file");
        }

        String sha256 = tachographStorage.calculateSha256(data);
        String fileName = result.getSuggestedFileName();
        if (fileName == null || fileName.isBlank()) {
            fileName = String.format("%s_%d_%tY%<tm%<td%<tH%<tM%<tS.DDD",
                    TachographDownloadJob.TYPE_DRIVER.equals(job.getDownloadType()) ? "C" : "M",
                    job.getDeviceId(), new Date());
        }

        Path tempFile = tachographStorage.createTempFile();
        try {
            tachographStorage.writeBytes(tempFile, data);
            Path finalPath = tachographStorage.resolveFinalPath(groupId, job.getDeviceId(), fileName);
            tachographStorage.moveTempToFinal(tempFile, finalPath);

            DddMetadata metadata = result.getMetadata();

            TachographFile file = new TachographFile();
            file.setDownloadJobId(job.getId());
            file.setDeviceId(job.getDeviceId());
            file.setGroupId(groupId);
            file.setFileName(fileName);
            file.setFileType(job.getDownloadType());
            file.setFileSize(data.length);
            file.setSha256(sha256);
            file.setStoragePath(finalPath.toString());
            file.setClientType(result.getClientType());
            file.setDownloadedAt(result.getDownloadedAt() != null ? result.getDownloadedAt() : new Date());
            file.setCreatedAt(new Date());
            file.setProcessedAt(new Date());

            if (metadata != null) {
                file.setVehicleRegistration(metadata.getVehicleRegistrationNumber());
                file.setVehicleIdentification(metadata.getVehicleIdentificationNumber());
                file.setVehicleUnitSerial(metadata.getVehicleUnitSerialNumber());
                file.setCardNumber(metadata.getCardNumber());
                file.setPeriodFrom(metadata.getDownloadablePeriodFrom());
                file.setPeriodTo(metadata.getDownloadablePeriodTo());
                file.setGeneration(metadata.getGeneration());
                file.setBlocks(String.join(",", metadata.getBlocks()));
                file.setValidationStatus(metadata.getWarnings().isEmpty()
                        ? TachographFile.VALIDATION_VALID : TachographFile.VALIDATION_VALID);
                if (!metadata.getWarnings().isEmpty()) {
                    file.setValidationMessage(String.join("; ", metadata.getWarnings()));
                }
            } else {
                file.setValidationStatus(TachographFile.VALIDATION_PENDING);
            }

            long fileId = storage.addObject(file, new Request(new Columns.Exclude("id")));
            file.setId(fileId);

            job.setFileId(fileId);
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));

            LOGGER.info("Tachograph file {} stored for job {} at {} ({} bytes, sha256 {})",
            LOGGER.info("Stored {} for job {} at {} ({} bytes, sha256 {})",
                    fileName, job.getId(), finalPath, data.length, sha256);
            return file;

        } finally {
            try {
                Files.deleteIfExists(tempFile);
            } catch (IOException ignored) {
                // The temporary file has already been moved in the normal case.
            }
        }
    }

    /** Records the download against the device schedule and moves the next due date forward. */
    private void markDownloaded(TachographDownloadJob job) throws StorageException {
        TachographConfiguration configuration = getConfiguration(job.getDeviceId());
        Date now = new Date();
        if (TachographDownloadJob.TYPE_DRIVER.equals(job.getDownloadType())) {
            configuration.setLastDriverDownload(now);
            configuration.setNextDriverDownload(addDays(now, driverInterval(configuration)));
        } else {
            configuration.setLastVehicleDownload(now);
            configuration.setNextVehicleDownload(addDays(now, vehicleInterval(configuration)));
        }
        configuration.setUpdatedAt(now);

        if (configuration.getId() == 0) {
            configuration.setCreatedAt(now);
            storage.addObject(configuration, new Request(new Columns.Exclude("id")));
        } else {
            storage.updateObject(configuration,
                    new Request(new Columns.Exclude("id"), new Condition.Equals("id", configuration.getId())));
        }
    }

    private void handleFailure(TachographDownloadJob job, String errorCode, String message) throws StorageException {
        // Non-retryable errors
        if (TachographDownloadJob.ERROR_INVALID_FILE.equals(errorCode)
                || TachographDownloadJob.ERROR_PERMISSION_DENIED.equals(errorCode)
                || TachographDownloadJob.ERROR_PROTOCOL_SPEC_MISSING.equals(errorCode)) {
            job.setStatus(TachographDownloadJob.STATUS_FAILED);
            job.setErrorCode(errorCode);
            job.setErrorMessage(message);
            job.setFailedAt(new Date());
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));
            LOGGER.warn("Tachograph job {} failed permanently: {} - {}", job.getId(), errorCode, message);
            return;
    /** Hands a stored file to the delivery queue, without letting that fail the download. */
    private void queueForwarding(TachographFile file, TachographDownloadJob job) {
        try {
            Device device = storage.getObject(Device.class,
                    new Request(new Columns.All(), new Condition.Equals("id", job.getDeviceId())));
            forwardService.enqueue(file, device);
        } catch (Exception e) {
            LOGGER.warn("Could not queue {} for delivery; it is stored and can be re-queued",
                    file.getFileName(), e);
        }
    }

    // -----------------------------------------------------------------------
    // Failure and retry
    // -----------------------------------------------------------------------

    private void handleFailure(TachographDownloadJob job, String errorCode, String message)
            throws StorageException {

        Date now = new Date();
        job.setErrorCode(errorCode);
        job.setErrorMessage(message);
        job.setUpdatedAt(now);

        int[] backoff = parseRetryDelays(config.getString(Keys.TACHO_RETRY_DELAYS));
        boolean permanent = PERMANENT_ERRORS.contains(errorCode);
        boolean exhausted = job.getRetryCount() >= Math.min(MAX_RETRIES, backoff.length);

        if (permanent || exhausted) {
            job.setStatus(TachographDownloadJob.STATUS_FAILED);
            job.setErrorCode(errorCode);
            job.setErrorMessage(message);
            job.setFailedAt(new Date());
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));
            LOGGER.warn("Tachograph job {} failed after {} retries: {} - {}",
                    job.getId(), job.getRetryCount(), errorCode, message);
            job.setProgressDetail("Failed");
            job.setFailedAt(now);
            job.setNextRetryAt(null);
            save(job);
            auditService.recordSystem(job.getDeviceId(), TachographAudit.ACTION_DOWNLOAD_FAILED,
                    "Job " + job.getId() + " failed: " + errorCode + " - " + message,
                    TachographAuditService.ACTOR_SYSTEM);
            LOGGER.warn("Tachograph job {} failed{}: {} - {}", job.getId(),
                    permanent ? " permanently" : " after " + job.getRetryCount() + " retries",
                    errorCode, message);
            return;
        }

        int delaySeconds = backoff[Math.min(job.getRetryCount(), backoff.length - 1)];
        job.setRetryCount(job.getRetryCount() + 1);
        job.setStatus(TachographDownloadJob.STATUS_QUEUED);
        job.setErrorCode(errorCode);
        job.setErrorMessage(message);
        job.setNextRetryAt(new Date(System.currentTimeMillis() + (long) delaySeconds * 1000));
        job.setUpdatedAt(new Date());
        storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));
        LOGGER.info("Tachograph job {} scheduled for retry #{} in {}s: {} - {}",
        job.setProgress(0);
        job.setProgressDetail("Waiting to retry");
        job.setNextRetryAt(new Date(now.getTime() + delaySeconds * 1000L));
        save(job);
        LOGGER.info("Tachograph job {} will retry (attempt {}) in {} s: {} - {}",
                job.getId(), job.getRetryCount(), delaySeconds, errorCode, message);
    }

    /** Runs jobs whose retry time has arrived. Called by the scheduler. */
    public void processRetries() throws StorageException {
        Date now = new Date();
        for (TachographDownloadJob job : storage.getObjects(
                TachographDownloadJob.class,
                new Request(new Columns.All(),
                        new Condition.Equals("status", TachographDownloadJob.STATUS_QUEUED)))) {

            if (running.containsKey(job.getId())) {
                continue;
            }
            if (job.getNextRetryAt() == null || !job.getNextRetryAt().after(now)) {
                executeAsync(job.getId());
            }
        }
    }

    /**
     * Re-queues jobs that were mid-flight when the server stopped. Their device tunnel and card
     * session are long gone, so they start again rather than trying to resume.
     */
    public void recoverStaleJobs() throws StorageException {
        for (TachographDownloadJob job : storage.getObjects(
                TachographDownloadJob.class, new Request(new Columns.All()))) {

            String status = job.getStatus();
            boolean interrupted = TachographDownloadJob.STATUS_REQUESTING.equals(status)
                    || TachographDownloadJob.STATUS_DOWNLOADING.equals(status)
                    || TachographDownloadJob.STATUS_PROCESSING.equals(status)
                    || TachographDownloadJob.STATUS_WAITING_FOR_DEVICE.equals(status)
                    || TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE.equals(status);

            if (interrupted) {
                job.setStatus(TachographDownloadJob.STATUS_QUEUED);
                job.setProgress(0);
                job.setProgressDetail("Restarting after a server restart");
                job.setNextRetryAt(new Date());
                job.setUpdatedAt(new Date());
                save(job);
                LOGGER.info("Recovered tachograph job {} after a restart", job.getId());
            }
        }
    }

    // -----------------------------------------------------------------------
    // Job queries and cancellation
    // -----------------------------------------------------------------------

    public TachographDownloadJob getJob(long jobId) throws StorageException {
        return storage.getObject(TachographDownloadJob.class,
                new Request(new Columns.All(), new Condition.Equals("id", jobId)));
    }

    /**
     * Jobs the user may see, newest first.
     *
     * @param deviceId restrict to one device, or null for every device the user can see
     */
    public List<TachographDownloadJob> getJobs(
            long userId, boolean administrator, Long deviceId, String status,
            Date from, Date to, int limit) throws StorageException {

        int effectiveLimit = limit > 0 ? Math.min(limit, 1000) : 100;

        Condition condition = null;
        if (deviceId != null) {
            condition = new Condition.Equals("deviceid", deviceId);
        }
        if (status != null && !status.isBlank()) {
            Condition statusCondition = new Condition.Equals("status", status);
            condition = condition == null ? statusCondition : new Condition.And(condition, statusCondition);
        }

        List<TachographDownloadJob> jobs = storage.getObjects(TachographDownloadJob.class,
                new Request(new Columns.All(), condition, new Order("id", true, effectiveLimit)));

        Set<Long> visible = administrator ? null : accessibleDeviceIds(userId);
        Map<Long, String> deviceNames = deviceNames();

        List<TachographDownloadJob> result = new ArrayList<>();
        for (TachographDownloadJob job : jobs) {
            String s = job.getStatus();
            if (TachographDownloadJob.STATUS_REQUESTING.equals(s)
                    || TachographDownloadJob.STATUS_DOWNLOADING.equals(s)
                    || TachographDownloadJob.STATUS_PROCESSING.equals(s)) {
                job.setStatus(TachographDownloadJob.STATUS_QUEUED);
                job.setErrorCode(null);
                job.setErrorMessage("Recovered after server restart");
                job.setUpdatedAt(new Date());
                storage.updateObject(job, new Request(
                        new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));
                LOGGER.info("Recovered stale tachograph job {}", job.getId());
                executeAsync(job.getId());
            } else if (TachographDownloadJob.STATUS_QUEUED.equals(s)
                    || TachographDownloadJob.STATUS_WAITING_FOR_DEVICE.equals(s)
                    || TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE.equals(s)) {
                executeAsync(job.getId());
            if (visible != null && !visible.contains(job.getDeviceId())) {
                continue;
            }
            if (from != null && job.getCreatedAt() != null && job.getCreatedAt().before(from)) {
                continue;
            }
            if (to != null && job.getCreatedAt() != null && job.getCreatedAt().after(to)) {
                continue;
            }
            job.setDeviceName(deviceNames.get(job.getDeviceId()));
            result.add(job);
        }
        return result;
    }

    /**
     * Asks a job to stop. A queued job stops immediately; a running one stops at the next safe
     * point rather than being killed part way through writing a file.
     */
    public void cancelJob(long jobId, long userId) throws StorageException, TachographException {
        TachographDownloadJob job = getJob(jobId);
        if (job == null) {
            throw new TachographException("TACHO_NOT_FOUND", "Job not found: " + jobId);
        }
        if (!isActive(job.getStatus())) {
            return;
        }

        AtomicBoolean flag = running.get(jobId);
        if (flag != null) {
            flag.set(true);
            job.setCancelRequested(true);
            job.setProgressDetail("Cancelling");
            job.setUpdatedAt(new Date());
            save(job);
            LOGGER.info("Tachograph job {} asked to cancel by user {}", jobId, userId);
        } else {
            job.setStatus(TachographDownloadJob.STATUS_CANCELLED);
            job.setCancelRequested(true);
            job.setProgressDetail("Cancelled");
            job.setNextRetryAt(null);
            job.setUpdatedAt(new Date());
            save(job);
            LOGGER.info("Tachograph job {} cancelled before starting, by user {}", jobId, userId);
        }

        auditService.record(userId, job.getDeviceId(), TachographAudit.ACTION_DOWNLOAD_CANCELLED,
                "Job " + jobId + " cancelled");
    }

    // -----------------------------------------------------------------------
    // Files
    // -----------------------------------------------------------------------

    public TachographFile getFile(long fileId) throws StorageException {
        return storage.getObject(TachographFile.class,
                new Request(new Columns.All(), new Condition.Equals("id", fileId)));
    }

    /** Files the user may see, newest first. */
    public List<TachographFile> getFiles(
            long userId, boolean administrator, Long deviceId, String fileType, int limit)
            throws StorageException {

        int effectiveLimit = limit > 0 ? Math.min(limit, 1000) : 100;

        Condition condition = null;
        if (deviceId != null) {
            condition = new Condition.Equals("deviceid", deviceId);
        }
        if (fileType != null && !fileType.isBlank()) {
            Condition typeCondition = new Condition.Equals("filetype", fileType);
            condition = condition == null ? typeCondition : new Condition.And(condition, typeCondition);
        }

        List<TachographFile> files = storage.getObjects(TachographFile.class,
                new Request(new Columns.All(), condition, new Order("id", true, effectiveLimit)));

        Set<Long> visible = administrator ? null : accessibleDeviceIds(userId);
        Map<Long, String> deviceNames = deviceNames();

        List<TachographFile> result = new ArrayList<>();
        for (TachographFile file : files) {
            if (visible != null && !visible.contains(file.getDeviceId())) {
                continue;
            }
            file.setDeviceName(deviceNames.get(file.getDeviceId()));
            result.add(file);
        }
        return result;
    }

    /**
     * Deletes a stored file and its record.
     *
     * <p>Note that operators are required to keep tachograph data for a year, so this is
     * deliberately an explicit administrator action rather than anything automatic.
     */
    public void deleteFile(long fileId, long userId) throws StorageException {
        TachographFile file = getFile(fileId);
        if (file == null) {
            return;
        }
        try {
            Files.deleteIfExists(Path.of(file.getStoragePath()));
        } catch (IOException e) {
            LOGGER.warn("Could not remove {} from disk", file.getStoragePath(), e);
        }
        storage.removeObject(TachographFile.class, new Request(new Condition.Equals("id", fileId)));
        auditService.record(userId, file.getDeviceId(), TachographAudit.ACTION_FILE_DELETED,
                "File " + file.getFileName() + " deleted");
        LOGGER.info("Tachograph file {} deleted by user {}", file.getFileName(), userId);
    }

    // -----------------------------------------------------------------------
    // Client and provider selection
    // -----------------------------------------------------------------------

    private boolean isSimulatorEnabled() {
        return config.getBoolean(Keys.TACHO_ENABLED) && config.getBoolean(Keys.TACHO_SIMULATOR);
    }

    /**
     * The authentication provider to use, or null when no company card is in play.
     *
     * <p>An installation that has paired any bridge is taken to need card authentication, and a
     * download for a vehicle with no usable bridge then fails rather than proceeding: having set
     * up a card and then not having it available is a fault to report, not something to skip
     * past quietly. An installation with no bridges at all does not attempt authentication.
     */
    private TachographAuthenticationProvider resolveAuthProvider() {
        if (isSimulatorEnabled()) {
            return mockAuthProvider;
        }
        if (matched == null) {
            throw new TachographException("INVALID_PAIRING_CODE", "Invalid or expired pairing code");
        }
        matched.setBridgeId(bridgeId);
        matched.setName(name);
        matched.setSoftwareVersion(softwareVersion);
        matched.setStatus(TachographBridge.STATUS_ONLINE);
        String token = java.util.UUID.randomUUID().toString();
        matched.setTokenHash(hashSha256(token));
        matched.setLastSeenAt(new Date());
        matched.setLastHeartbeat(new Date());
        matched.setPairingCodeHash(null);
        matched.setPairingCodeExpiresAt(null);
        storage.updateObject(matched, new Request(
                new Columns.Exclude("id"), new Condition.Equals("id", matched.getId())));
        // Return with token in a transient field (reuse tokenHash field for response only if needed)
        // The caller receives the raw token via the bridge's tokenHash? For MVP we set tokenHash to the
        // hash and return the raw token in the bridge name? Instead, put token in softwareVersion transient?
        // Simpler: set tokenHash to raw token for the response, then re-hash on next heartbeat.
        // For MVP we store the hash and return the raw token in a map via the resource.
        // To keep the model clean, we store the hash and the resource returns the raw token separately.
        // Here we set a transient attribute for the resource to read.
        matched.setTokenHash(token); // raw token for immediate response; will be hashed on next heartbeat
        LOGGER.info("Bridge {} registered for group {}", bridgeId, matched.getGroupId());
        return matched;
    }

    public Map<String, Object> heartbeat(long bridgeId, String token, Map<String, Object> body)
            throws StorageException, TachographException {
        TachographBridge bridge = getBridge(bridgeId);
        if (bridge == null) {
            throw new TachographException("NOT_FOUND", "Bridge not found: " + bridgeId);
        }
        if (token == null || !hashSha256(token).equals(bridge.getTokenHash())
                && !token.equals(bridge.getTokenHash())) {
            // allow raw token match for the first heartbeat after registration
            boolean ok = false;
            if (bridge.getTokenHash() != null) {
                ok = hashSha256(token).equals(bridge.getTokenHash()) || token.equals(bridge.getTokenHash());
            }
            if (!ok) {
                throw new TachographException("UNAUTHORIZED", "Invalid bridge token");
            }
            // migrate raw token to hash on first successful heartbeat
            if (token.equals(bridge.getTokenHash())) {
                bridge.setTokenHash(hashSha256(token));
            }
        return hasAnyBridge() ? bridgeAuthProvider : null;
    }

    private boolean hasAnyBridge() {
        try {
            return !storage.getObjects(TachographBridge.class,
                    new Request(new Columns.Include("id"))).isEmpty();
        } catch (StorageException e) {
            LOGGER.warn("Could not check for tacho bridges; continuing without card authentication", e);
            return false;
        }
    }

    private TachographDeviceClient resolveDeviceClient(long deviceId) throws TachographException {
        if (isSimulatorEnabled() && simulatedClient.canHandle(deviceId)) {
            return simulatedClient;
        }
        if (fmc650Client.canHandle(deviceId)) {
            return fmc650Client;
        }
        storage.updateObject(bridge, new Request(
                new Columns.Exclude("id"), new Condition.Equals("id", bridge.getId())));
        throw new TachographException(
                TachographDownloadJob.ERROR_PROTOCOL_SPEC_MISSING,
                "No tachograph transport is configured. Set tacho.tunnel.port so vehicles can "
                        + "open a data tunnel, or enable tacho.simulator for testing.");
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private void save(TachographDownloadJob job) throws StorageException {
        storage.updateObject(job,
                new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));
    }

    private long resolveGroupId(long deviceId) throws StorageException {
        Device device = storage.getObject(Device.class,
                new Request(new Columns.All(), new Condition.Equals("id", deviceId)));
        return device != null ? device.getGroupId() : 0;
    }

    /** Device identifiers the user has permission to see. */
    public Set<Long> accessibleDeviceIds(long userId) throws StorageException {
        Set<Long> ids = new HashSet<>();
        for (Device device : storage.getObjects(Device.class, new Request(
                new Columns.Include("id"),
                new Condition.Permission(User.class, userId, Device.class)))) {
            ids.add(device.getId());
        }
        return ids;
    }

    private Map<Long, String> deviceNames() throws StorageException {
        return storage.getObjects(Device.class, new Request(new Columns.All())).stream()
                .collect(Collectors.toMap(Device::getId, Device::getName, (first, second) -> first));
    }

    private Date addDays(Date from, int days) {
        Date base = from != null ? from : new Date();
        return new Date(base.getTime() + days * 24L * 60 * 60 * 1000);
    }

    private boolean sameInstant(Date left, Date right) {
        if (left == null || right == null) {
            return left == right;
        }
        return left.getTime() == right.getTime();
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
}
