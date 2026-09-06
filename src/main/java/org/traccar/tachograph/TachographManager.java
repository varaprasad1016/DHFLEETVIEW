/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.tachograph;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.model.Device;
import org.traccar.model.Group;
import org.traccar.model.TachographBridge;
import org.traccar.model.TachographConfiguration;
import org.traccar.model.TachographDownloadJob;
import org.traccar.model.TachographFile;
import org.traccar.session.ConnectionManager;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Order;
import org.traccar.storage.query.Request;

import java.util.Date;
import java.util.List;
import java.util.Map;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@Singleton
public class TachographManager {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographManager.class);

    private final Config config;
    private final Storage storage;
    private final TachographStorage tachographStorage;
    private final ConnectionManager connectionManager;
    private final MockAuthenticationProvider mockAuthProvider;
    private final SimulatedTachographDeviceClient simulatedClient;
    private final ObjectMapper objectMapper;

    private final ExecutorService executor;

    @Inject
    public TachographManager(
            Config config,
            Storage storage,
            TachographStorage tachographStorage,
            ConnectionManager connectionManager,
            MockAuthenticationProvider mockAuthProvider,
            SimulatedTachographDeviceClient simulatedClient,
            ObjectMapper objectMapper) {
        this.config = config;
        this.storage = storage;
        this.tachographStorage = tachographStorage;
        this.connectionManager = connectionManager;
        this.mockAuthProvider = mockAuthProvider;
        this.simulatedClient = simulatedClient;
        this.objectMapper = objectMapper;
        this.executor = Executors.newFixedThreadPool(4, r -> {
            Thread t = new Thread(r, "tacho-download");
            t.setDaemon(true);
            return t;
        });
    }

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------

    public TachographConfiguration getConfiguration(long deviceId) throws StorageException {
        TachographConfiguration config = storage.getObject(
                TachographConfiguration.class,
                new Request(new Columns.All(), new Condition.Equals("deviceid", deviceId)));
        if (config == null) {
            config = new TachographConfiguration();
            config.setDeviceId(deviceId);
            config.setEnabled(false);
            config.setDriverDownloadEnabled(false);
            config.setVehicleDownloadEnabled(false);
            config.setDriverDownloadIntervalDays(28);
            config.setVehicleDownloadIntervalDays(90);
            // not persisted until explicitly saved
        }
        return config;
    }

    public void saveConfiguration(TachographConfiguration configuration) throws StorageException {
        configuration.setUpdatedAt(new Date());
        TachographConfiguration existing = storage.getObject(
                TachographConfiguration.class,
                new Request(new Columns.All(), new Condition.Equals("deviceid", configuration.getDeviceId())));
        if (existing == null) {
            configuration.setCreatedAt(new Date());
            storage.addObject(configuration, new Request(new Columns.Exclude("id")));
        } else {
            configuration.setId(existing.getId());
            storage.updateObject(configuration, new Request(
                    new Columns.Exclude("id"),
                    new Condition.Equals("id", existing.getId())));
        }
    }

    // -----------------------------------------------------------------------
    // Download jobs
    // -----------------------------------------------------------------------

    public synchronized TachographDownloadJob createDownloadJob(
            long deviceId, String downloadType, long requestedBy,
            Date from, Date to) throws StorageException, TachographException {

        if (!TachographDownloadJob.TYPE_DRIVER.equals(downloadType)
                && !TachographDownloadJob.TYPE_VEHICLE.equals(downloadType)) {
            throw new TachographException(
                    TachographException.INVALID_FILE, "Invalid download type: " + downloadType);
        }

        // duplicate prevention
        List<TachographDownloadJob> active = storage.getObjects(
                TachographDownloadJob.class,
                new Request(new Columns.All(),
                        new Condition.Equals("deviceid", deviceId)));
        for (TachographDownloadJob job : active) {
            String s = job.getStatus();
            if (TachographDownloadJob.STATUS_QUEUED.equals(s)
                    || TachographDownloadJob.STATUS_WAITING_FOR_DEVICE.equals(s)
                    || TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE.equals(s)
                    || TachographDownloadJob.STATUS_REQUESTING.equals(s)
                    || TachographDownloadJob.STATUS_DOWNLOADING.equals(s)
                    || TachographDownloadJob.STATUS_PROCESSING.equals(s)) {
                if (downloadType.equals(job.getDownloadType())) {
                    throw new TachographException(
                            TachographDownloadJob.ERROR_ALREADY_RUNNING,
                            "Download already running for device " + deviceId + " type " + downloadType);
                }
            }
        }

        TachographDownloadJob job = new TachographDownloadJob();
        job.setDeviceId(deviceId);
        job.setRequestedBy(requestedBy);
        job.setDownloadType(downloadType);
        job.setRequestedFrom(from);
        job.setRequestedTo(to);
        job.setStatus(TachographDownloadJob.STATUS_QUEUED);
        job.setProgress(0);
        job.setRetryCount(0);
        Date now = new Date();
        job.setQueuedAt(now);
        job.setCreatedAt(now);
        job.setUpdatedAt(now);

        long id = storage.addObject(job, new Request(new Columns.Exclude("id")));
        job.setId(id);

        LOGGER.info("Tachograph job {} queued for device {} type {}", id, deviceId, downloadType);

        executeAsync(id);
        return job;
    }

    public TachographDownloadJob getJob(long jobId) throws StorageException {
        return storage.getObject(
                TachographDownloadJob.class,
                new Request(new Columns.All(), new Condition.Equals("id", jobId)));
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

    public void executeAsync(long jobId) {
        executor.submit(() -> {
            try {
                executeJob(jobId);
            } catch (Exception e) {
                LOGGER.warn("Tachograph job {} execution error", jobId, e);
            }
        });
    }

    private void executeJob(long jobId) throws StorageException {
        TachographDownloadJob job = getJob(jobId);
        if (job == null) {
            return;
        }
        // only execute queuable states
        String status = job.getStatus();
        if (!TachographDownloadJob.STATUS_QUEUED.equals(status)
                && !TachographDownloadJob.STATUS_WAITING_FOR_DEVICE.equals(status)
                && !TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE.equals(status)) {
            // retry handling may re-queue as QUEUED
            if (!TachographDownloadJob.STATUS_QUEUED.equals(status)) {
                return;
            }
        }

        job.setStatus(TachographDownloadJob.STATUS_REQUESTING);
        job.setStartedAt(new Date());
        job.setUpdatedAt(new Date());
        storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));

        String authToken = null;
        try {
            // device availability
            if (connectionManager.getDeviceSession(job.getDeviceId()) == null) {
                // For FMC650 remote download the device must have an active TCP session.
                // In simulator mode we treat it as online when the simulator is enabled.
                if (!isSimulatorEnabled()) {
                    handleFailure(job, TachographDownloadJob.ERROR_DEVICE_OFFLINE, "Device offline");
                    return;
                }
            }

            // bridge/card authentication
            long groupId = resolveGroupId(job.getDeviceId());
            TachographAuthenticationProvider authProvider = resolveAuthProvider(groupId);
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

                authProvider.authenticate(authToken, jobId);
            } else {
                job.setStatus(TachographDownloadJob.STATUS_DOWNLOADING);
                job.setProgress(10);
                job.setUpdatedAt(new Date());
                storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));
            }

            // device download
            TachographDeviceClient client = resolveDeviceClient(job.getDeviceId());
            TachographDownloadResult result = client.download(job.getDeviceId(), job.getDownloadType());

            job.setStatus(TachographDownloadJob.STATUS_PROCESSING);
            job.setProgress(70);
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));

            // storage
            storeResult(job, result);

            job.setStatus(TachographDownloadJob.STATUS_COMPLETED);
            job.setProgress(100);
            job.setCompletedAt(new Date());
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", jobId)));

            // update configuration next-download
            updateNextDownload(job);

            LOGGER.info("Tachograph job {} completed for device {}", jobId, job.getDeviceId());

        } catch (TachographException e) {
            handleFailure(job, e.getErrorCode(), e.getMessage());
        } catch (Exception e) {
            handleFailure(job, TachographDownloadJob.ERROR_STORAGE, e.getMessage());
        } finally {
            if (authToken != null) {
                try {
                    long groupId = resolveGroupId(job.getDeviceId());
                    TachographAuthenticationProvider provider = resolveAuthProvider(groupId);
                    if (provider != null) {
                        provider.closeSession(authToken);
                    }
                } catch (Exception e) {
                    LOGGER.warn("Failed to close auth session for job {}", jobId, e);
                }
            }
        }
    }

    private void storeResult(TachographDownloadJob job, TachographDownloadResult result) throws Exception {
        byte[] data = result.getData();
        if (data == null || data.length == 0) {
            throw new TachographException(TachographDownloadJob.ERROR_INVALID_FILE, "Empty DDD file received");
        }

        String sha256 = tachographStorage.calculateSha256(data);
        String fileName = result.getSuggestedFileName();
        if (fileName == null || fileName.isBlank()) {
            fileName = String.format("%s_%tY%<tm%<td%<tH%<tM%<tS_%d.DDD",
                    TachographDownloadJob.TYPE_DRIVER.equals(job.getDownloadType()) ? "C" : "M",
                    new Date(), job.getDeviceId());
        }

        long groupId = resolveGroupId(job.getDeviceId());
        Path tempFile = tachographStorage.createTempFile();
        try {
            tachographStorage.writeBytes(tempFile, data);
            String validationStatus = TachographFile.VALIDATION_VALID;
            // Basic DDD sanity: simulated files are marked with the marker; real DDD validation
            // would invoke a parser here.
            if (data.length < 10) {
                validationStatus = TachographFile.VALIDATION_INVALID;
            }

            Path finalPath = tachographStorage.resolveFinalPath(groupId, job.getDeviceId(), fileName);
            tachographStorage.moveTempToFinal(tempFile, finalPath);

            TachographFile file = new TachographFile();
            file.setDownloadJobId(job.getId());
            file.setDeviceId(job.getDeviceId());
            file.setFileName(fileName);
            file.setFileType(job.getDownloadType());
            file.setFileSize(data.length);
            file.setSha256(sha256);
            file.setStoragePath(finalPath.toString());
            file.setValidationStatus(validationStatus);
            file.setDownloadedAt(result.getDownloadedAt() != null ? result.getDownloadedAt() : new Date());
            file.setCreatedAt(new Date());

            long fileId = storage.addObject(file, new Request(new Columns.Exclude("id")));
            file.setId(fileId);

            job.setFileId(fileId);
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));

            LOGGER.info("Tachograph file {} stored for job {} at {} ({} bytes, sha256 {})",
                    fileName, job.getId(), finalPath, data.length, sha256);

        } finally {
            try {
                Files.deleteIfExists(tempFile);
            } catch (IOException ignored) {
            }
        }
    }

    private void updateNextDownload(TachographDownloadJob job) throws StorageException {
        TachographConfiguration cfg = getConfiguration(job.getDeviceId());
        Date now = new Date();
        if (TachographDownloadJob.TYPE_DRIVER.equals(job.getDownloadType())) {
            cfg.setLastDriverDownload(now);
            int interval = cfg.getDriverDownloadIntervalDays() > 0
                    ? cfg.getDriverDownloadIntervalDays()
                    : config.getInteger(Keys.TACHO_DRIVER_INTERVAL);
            cfg.setNextDriverDownload(new Date(now.getTime() + (long) interval * 24 * 3600 * 1000));
        } else {
            cfg.setLastVehicleDownload(now);
            int interval = cfg.getVehicleDownloadIntervalDays() > 0
                    ? cfg.getVehicleDownloadIntervalDays()
                    : config.getInteger(Keys.TACHO_VEHICLE_INTERVAL);
            cfg.setNextVehicleDownload(new Date(now.getTime() + (long) interval * 24 * 3600 * 1000));
        }
        saveConfiguration(cfg);
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
        }

        int maxRetries = 5;
        String delays = config.getString(Keys.TACHO_RETRY_DELAYS);
        int[] backoff = parseRetryDelays(delays);

        if (job.getRetryCount() >= Math.min(maxRetries, backoff.length)) {
            job.setStatus(TachographDownloadJob.STATUS_FAILED);
            job.setErrorCode(errorCode);
            job.setErrorMessage(message);
            job.setFailedAt(new Date());
            job.setUpdatedAt(new Date());
            storage.updateObject(job, new Request(new Columns.Exclude("id"), new Condition.Equals("id", job.getId())));
            LOGGER.warn("Tachograph job {} failed after {} retries: {} - {}",
                    job.getId(), job.getRetryCount(), errorCode, message);
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
                job.getId(), job.getRetryCount(), delaySeconds, errorCode, message);
    }

    private int[] parseRetryDelays(String value) {
        if (value == null || value.isBlank()) {
            return new int[]{30, 120, 600};
        }
        String[] parts = value.split(",");
        int[] result = new int[parts.length];
        for (int i = 0; i < parts.length; i++) {
            try {
                result[i] = Integer.parseInt(parts[i].trim());
            } catch (NumberFormatException e) {
                result[i] = 120;
            }
        }
        return result;
    }

    private boolean isSimulatorEnabled() {
        return Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_ENABLED))
                && Boolean.TRUE.equals(config.getBoolean(Keys.TACHO_SIMULATOR));
    }

    private TachographAuthenticationProvider resolveAuthProvider(long groupId) {
        if (isSimulatorEnabled()) {
            return mockAuthProvider;
        }
        // Real bridge auth not yet implemented - report spec missing.
        // The job will fail with PROTOCOL_SPEC_MISSING until the Tacho Bridge
        // and real card authentication are implemented per tachoauth.txt.
        return null;
    }

    private TachographDeviceClient resolveDeviceClient(long deviceId) throws TachographException {
        if (isSimulatorEnabled() && simulatedClient.canHandle(deviceId)) {
            return simulatedClient;
        }
        throw new TachographException(
                TachographDownloadJob.ERROR_PROTOCOL_SPEC_MISSING,
                "Real FMC650 tachograph protocol not implemented. Enable tacho.simulator for testing, "
                        + "or provide the Teltonika/tachograph specification per tacho.txt. deviceId=" + deviceId);
    }

    private long resolveGroupId(long deviceId) throws StorageException {
        Device device = storage.getObject(Device.class, new Request(
                new Columns.All(), new Condition.Equals("id", deviceId)));
        if (device != null && device.getGroupId() != 0) {
            return device.getGroupId();
        }
        return 0;
    }

    public void recoverStaleJobs() throws StorageException {
        List<TachographDownloadJob> jobs = storage.getObjects(
                TachographDownloadJob.class, new Request(new Columns.All()));
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
            }
        }
    }

    public void processRetries() throws StorageException {
        List<TachographDownloadJob> jobs = storage.getObjects(
                TachographDownloadJob.class,
                new Request(new Columns.All(), new Condition.Equals("status", TachographDownloadJob.STATUS_QUEUED)));
        Date now = new Date();
        for (TachographDownloadJob job : jobs) {
            if (job.getNextRetryAt() != null && !job.getNextRetryAt().after(now)) {
                LOGGER.info("Retrying tachograph job {} (attempt {})", job.getId(), job.getRetryCount());
                executeAsync(job.getId());
            }
        }
    }

    // -----------------------------------------------------------------------
    // Files
    // -----------------------------------------------------------------------

    public TachographFile getFile(long fileId) throws StorageException {
        return storage.getObject(
                TachographFile.class, new Request(new Columns.All(), new Condition.Equals("id", fileId)));
    }

    public List<TachographFile> getFiles(Long deviceId, int limit) throws StorageException {
        Request request;
        if (deviceId != null) {
            request = new Request(
                    new Columns.All(), new Condition.Equals("deviceid", deviceId),
                    new Order("id", true, limit));
        } else {
            request = new Request(new Columns.All(), null, new Order("id", true, limit));
        }
        return storage.getObjects(TachographFile.class, request);
    }

    // -----------------------------------------------------------------------
    // Bridges
    // -----------------------------------------------------------------------

    public List<TachographBridge> listBridges(long userId) throws StorageException {
        // For MVP: return all bridges visible to the user (group permission filtered by the
        // resource layer in a full implementation; here we return all for simplicity).
        return storage.getObjects(
                TachographBridge.class, new Request(new Columns.All()));
    }

    public TachographBridge getBridge(long bridgeId) throws StorageException {
        return storage.getObject(
                TachographBridge.class, new Request(new Columns.All(), new Condition.Equals("id", bridgeId)));
    }

    public String generatePairingCode(long groupId, String name, long userId) throws StorageException {
        String code = String.format("%06d", new java.util.Random().nextInt(1_000_000));
        String hash = hashSha256(code);
        TachographBridge bridge = new TachographBridge();
        bridge.setBridgeId("bridge-" + java.util.UUID.randomUUID());
        bridge.setGroupId(groupId);
        bridge.setName(name != null ? name : "Tacho Bridge");
        bridge.setStatus(TachographBridge.STATUS_OFFLINE);
        bridge.setPairingCodeHash(hash);
        bridge.setPairingCodeExpiresAt(new Date(System.currentTimeMillis() + 15 * 60 * 1000));
        bridge.setRegisteredAt(new Date());
        bridge.setLastSeenAt(new Date());
        storage.addObject(bridge, new Request(new Columns.Exclude("id")));
        LOGGER.info("Generated pairing code for group {} bridge {}", groupId, bridge.getBridgeId());
        return code;
    }

    public TachographBridge registerBridge(
            String pairingCode, String bridgeId, String name, String softwareVersion)
            throws StorageException, TachographException {
        String hash = hashSha256(pairingCode);
        List<TachographBridge> bridges = storage.getObjects(
                TachographBridge.class, new Request(new Columns.All()));
        TachographBridge matched = null;
        for (TachographBridge b : bridges) {
            if (hash.equals(b.getPairingCodeHash())
                    && b.getPairingCodeExpiresAt() != null
                    && b.getPairingCodeExpiresAt().after(new Date())) {
                matched = b;
                break;
            }
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
        }
        bridge.setLastHeartbeat(new Date());
        bridge.setLastSeenAt(new Date());
        bridge.setStatus(TachographBridge.STATUS_ONLINE);
        if (body != null) {
            if (body.get("readerStatus") != null) {
                bridge.setReaderStatus(body.get("readerStatus").toString());
            }
            if (body.get("cardStatus") != null) {
                bridge.setCardStatus(body.get("cardStatus").toString());
            }
            if (body.get("softwareVersion") != null) {
                bridge.setSoftwareVersion(body.get("softwareVersion").toString());
            }
        }
        storage.updateObject(bridge, new Request(
                new Columns.Exclude("id"), new Condition.Equals("id", bridge.getId())));

        Map<String, Object> response = new java.util.HashMap<>();
        response.put("status", "ok");
        // pending auth operations would be queried here in a full implementation
        return response;
    }

    private String hashSha256(String input) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(input.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
