/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
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
package org.traccar.api.resource;

import jakarta.annotation.security.PermitAll;
import jakarta.inject.Inject;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.StreamingOutput;

import org.traccar.api.BaseResource;
import org.traccar.model.Device;
import org.traccar.model.Group;
import org.traccar.model.TachographAudit;
import org.traccar.model.TachographBridge;
import org.traccar.model.TachographConfiguration;
import org.traccar.model.TachographDownloadJob;
import org.traccar.model.Position;
import org.traccar.model.TachographFile;
import org.traccar.model.User;
import org.traccar.model.TachographForward;
import org.traccar.model.TachographForwardTarget;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Order;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.TachographAuditService;
import org.traccar.tachograph.TachographBridgeManager;
import org.traccar.tachograph.TachographException;
import org.traccar.tachograph.TachographManager;
import org.traccar.tachograph.card.CardCommand;
import org.traccar.tachograph.card.CardIdentity;
import org.traccar.tachograph.card.CardResponse;
import org.traccar.tachograph.card.RemoteCardService;
import org.traccar.tachograph.forward.ForwardException;
import org.traccar.tachograph.forward.TachographForwardService;
import org.traccar.config.Config;
import org.traccar.config.Keys;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.Base64;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * REST API for the tachograph module.
 *
 * <p>Two different callers reach this resource. Operators arrive with a normal user session and
 * everything they touch is checked against their device and group permissions. Tacho bridges
 * arrive with a bridge token in a header and can only reach the endpoints under
 * {@code bridges/{id}/}, which never expose fleet data.
 */
@jakarta.ws.rs.Path("tachograph")
@Produces(MediaType.APPLICATION_JSON)
public class TachographResource extends BaseResource {

    // How far back the live view looks, and the most records it will read to
    // get there. A parked unit reports every few minutes and a driving one
    // every few seconds, so the limit is what actually bounds the work.
    private static final int LIVE_HOURS = 24;
    private static final int LIVE_MAX_HOURS = 168;
    private static final int LIVE_SCAN_LIMIT = 5000;
    private static final int LIVE_BULK_SCAN_LIMIT = 500;

    // Tachograph AVL IDs: the driver slots, their figures and the vehicle-side
    // elements, plus the 105xx block the newer figures live in.
    private static final Set<Integer> TACHO_IDS = Set.of(
            48, 52, 56, 57, 58, 59, 60, 61, 69, 77, 80, 122, 123, 124, 125,
            184, 185, 186, 187, 188, 189, 190, 195, 196, 197, 198, 528);
    private static final int TACHO_RANGE_FROM = 10500;
    private static final int TACHO_RANGE_TO = 10545;

    @Context
    private HttpServletRequest request;

    @Inject
    private Config config;

    @Inject
    private TachographManager tachographManager;

    @Inject
    private TachographBridgeManager bridgeManager;

    @Inject
    private TachographForwardService forwardService;

    @Inject
    private TachographAuditService auditService;

    @Inject
    private RemoteCardService cardService;

    // -----------------------------------------------------------------------
    // Overview
    // -----------------------------------------------------------------------

    /** Headline counts for the tachograph dashboard, over the devices the user can see. */
    @GET
    @Path("summary")
    public Map<String, Object> summary() throws StorageException {
        boolean administrator = isAdministrator();
        long userId = getUserId();

        List<TachographDownloadJob> jobs =
                tachographManager.getJobs(userId, administrator, null, null, null, null, 500);
        List<TachographFile> files =
                tachographManager.getFiles(userId, administrator, null, null, 500);
        List<TachographBridge> bridges = bridgeManager.list(userId, administrator);

        long active = jobs.stream().filter(job -> isActiveStatus(job.getStatus())).count();
        long failed = jobs.stream()
                .filter(job -> TachographDownloadJob.STATUS_FAILED.equals(job.getStatus())).count();
        long completed = jobs.stream()
                .filter(job -> TachographDownloadJob.STATUS_COMPLETED.equals(job.getStatus())).count();
        long bridgesReady = bridges.stream().filter(TachographBridge::getCardReady).count();
        long pendingDeliveries = forwardService.listForwards(
                null, TachographForward.STATUS_QUEUED, 500).size();
        long failedDeliveries = forwardService.listForwards(
                null, TachographForward.STATUS_FAILED, 500).size();

        Map<String, Object> summary = new HashMap<>();
        summary.put("activeDownloads", active);
        summary.put("completedDownloads", completed);
        summary.put("failedDownloads", failed);
        summary.put("files", files.size());
        summary.put("bridges", bridges.size());
        summary.put("bridgesReady", bridgesReady);
        summary.put("pendingDeliveries", pendingDeliveries);
        summary.put("failedDeliveries", failedDeliveries);
        summary.put("simulator", config.getBoolean(Keys.TACHO_SIMULATOR));
        summary.put("tunnelPort", config.getInteger(Keys.TACHO_TUNNEL_PORT));
        return summary;
    }

    private boolean isActiveStatus(String status) {
        return TachographDownloadJob.STATUS_QUEUED.equals(status)
                || TachographDownloadJob.STATUS_WAITING_FOR_DEVICE.equals(status)
                || TachographDownloadJob.STATUS_WAITING_FOR_BRIDGE.equals(status)
                || TachographDownloadJob.STATUS_REQUESTING.equals(status)
                || TachographDownloadJob.STATUS_DOWNLOADING.equals(status)
                || TachographDownloadJob.STATUS_PROCESSING.equals(status);
    }

    /** Returns the company/operator name read from the latest visible vehicle-unit file. */
    @GET
    @Path("company")
    public Map<String, String> companyName() throws StorageException {
        List<TachographFile> files = tachographManager.getFiles(
                getUserId(), isAdministrator(), null, TachographFile.TYPE_VEHICLE, 500);
        String name = files.stream()
                .map(TachographFile::getCompanyName)
                .filter(value -> value != null && !value.isBlank())
                .findFirst()
                .orElse("${title}");
        return Map.of("name", name);
    }

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------

    @GET
    @Path("configuration/{deviceId}")
    public TachographConfiguration getConfiguration(@PathParam("deviceId") long deviceId)
            throws StorageException {
        permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        return tachographManager.getConfiguration(deviceId);
    }

    @POST
    @Path("configuration/{deviceId}")
    @Consumes(MediaType.APPLICATION_JSON)
    public TachographConfiguration saveConfiguration(
            @PathParam("deviceId") long deviceId,
            TachographConfiguration configuration) throws StorageException {
        permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        configuration.setDeviceId(deviceId);
        return tachographManager.saveConfiguration(configuration, getUserId());
    }

    // -----------------------------------------------------------------------
    // Live tachograph state
    // -----------------------------------------------------------------------

    /**
     * The vehicle's tachograph state, merged from its recent records.
     *
     * A unit sends a tachograph value when it changes, so any one position
     * carries only what moved - and a parked lorry sends records with none of
     * them at all. Reading the latest position therefore shows nothing, which
     * is not the same as there being nothing to show: the driver's hours are
     * exactly as they were when the engine stopped.
     *
     * This walks back through the device's records, newest first, keeping the
     * first value it finds for each element - the state as last reported,
     * whatever the ignition is doing now. Merging here rather than in the app
     * keeps the history off the phone: a day of this unit is several thousand
     * records, and what comes back instead is about sixty values.
     */
    @GET
    @Path("live/{deviceId}")
    public Map<String, Object> getLive(
            @PathParam("deviceId") long deviceId,
            @QueryParam("hours") int hours) throws StorageException {
        permissionsService.checkPermission(Device.class, getUserId(), deviceId);

        Date to = new Date();
        long window = TimeUnit.HOURS.toMillis(hours > 0 ? Math.min(hours, LIVE_MAX_HOURS) : LIVE_HOURS);
        Date from = new Date(to.getTime() - window);

        var conditions = new LinkedList<Condition>();
        conditions.add(new Condition.Equals("deviceId", deviceId));
        conditions.add(new Condition.Between("fixTime", from, to));
        var positions = storage.getObjects(Position.class, new Request(
                new Columns.All(), Condition.merge(conditions),
                new Order("fixTime", true, LIVE_SCAN_LIMIT, 0)));

        Map<String, Object> values = new LinkedHashMap<>();
        Date recordedAt = null;
        for (Position position : positions) {
            for (var entry : position.getAttributes().entrySet()) {
                if (isTachoKey(entry.getKey()) && !values.containsKey(entry.getKey())) {
                    values.put(entry.getKey(), entry.getValue());
                    if (recordedAt == null) {
                        recordedAt = position.getFixTime();
                    }
                }
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("deviceId", deviceId);
        result.put("recordedAt", recordedAt);
        result.put("scanned", positions.size());
        result.put("attributes", values);
        return result;
    }

    /**
     * The same, for every vehicle the user can see, in one request.
     *
     * The vehicle list shows each driver beside their registration, and asking
     * per row would be a request per vehicle on every visit to the home screen.
     * Only units that could carry a tachograph are looked at - a camera-only
     * vehicle has nothing to merge - and the scan per vehicle is short, because
     * a stopped unit reports every few minutes and a few hundred records
     * therefore reach back a long way.
     */
    @GET
    @Path("live")
    public Map<String, Object> getLiveAll() throws StorageException {
        var devices = storage.getObjects(Device.class, new Request(
                new Columns.All(), new Condition.Permission(User.class, getUserId(), Device.class)));

        Date to = new Date();
        Date from = new Date(to.getTime() - TimeUnit.HOURS.toMillis(LIVE_HOURS));
        Map<String, Object> result = new LinkedHashMap<>();
        for (Device device : devices) {
            if (!couldHaveTachograph(device)) {
                continue;
            }
            var conditions = new LinkedList<Condition>();
            conditions.add(new Condition.Equals("deviceId", device.getId()));
            conditions.add(new Condition.Between("fixTime", from, to));
            var positions = storage.getObjects(Position.class, new Request(
                    new Columns.All(), Condition.merge(conditions),
                    new Order("fixTime", true, LIVE_BULK_SCAN_LIMIT, 0)));

            Map<String, Object> values = new LinkedHashMap<>();
            Date recordedAt = null;
            for (Position position : positions) {
                for (var entry : position.getAttributes().entrySet()) {
                    if (isTachoKey(entry.getKey()) && !values.containsKey(entry.getKey())) {
                        values.put(entry.getKey(), entry.getValue());
                        if (recordedAt == null) {
                            recordedAt = position.getFixTime();
                        }
                    }
                }
            }
            if (!values.isEmpty()) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("recordedAt", recordedAt);
                entry.put("attributes", values);
                result.put(String.valueOf(device.getId()), entry);
            }
        }
        return result;
    }

    /**
     * Whether this vehicle is worth scanning: it has a tracker on it, rather
     * than being a camera-only vehicle whose positions come from the DVR.
     */
    private static boolean couldHaveTachograph(Device device) {
        if (device.getString("trackerImei") != null || device.getString("trackerModel") != null) {
            return true;
        }
        String uniqueId = device.getUniqueId();
        return uniqueId != null && uniqueId.length() >= 15 && uniqueId.chars().allMatch(Character::isDigit);
    }

    /**
     * Whether an attribute is a tachograph element, by its Teltonika AVL ID.
     *
     * The same set exists in the web app (common/util/fmc650Tacho.js) and in
     * the tacho server (app/services/fmc650.py); all three have to move
     * together. Kept as a range plus a short list rather than every ID, because
     * what matters here is only "is this worth keeping", not what it means.
     */
    private static boolean isTachoKey(String key) {
        if (key == null || !key.startsWith("io")) {
            return false;
        }
        try {
            int id = Integer.parseInt(key.substring(2));
            return TACHO_IDS.contains(id) || (id >= TACHO_RANGE_FROM && id <= TACHO_RANGE_TO);
        } catch (NumberFormatException e) {
            return false;
        }
    }

    // -----------------------------------------------------------------------
    // Downloads
    // -----------------------------------------------------------------------

    @GET
    @Path("bridge/download")
    public Response downloadBridge() {
        java.io.File file = new java.io.File("media/tacho-bridge/TachoBridgeSetup.exe");
        if (!file.exists() || !file.isFile()) {
            return Response.status(Response.Status.NOT_FOUND)
                    .type(MediaType.APPLICATION_JSON)
                    .entity(Map.of("error",
                            "Tacho Bridge App installer is not available yet. Build it from the "
                            + "forked Tacho Bridge App and place it at "
                            + "media/tacho-bridge/TachoBridgeSetup.exe on the server."))
                    .build();
        }
        StreamingOutput output = out -> {
            try (InputStream in = new java.io.FileInputStream(file)) {
                in.transferTo(out);
            } catch (IOException e) {
                // client disconnected mid-download
            }
        };
        return Response.ok(output)
                .header("Content-Type", "application/octet-stream")
                .header("Content-Disposition", "attachment; filename=\"TachoBridgeSetup.exe\"")
                .build();
    }

    @POST
    @Path("download")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response createDownload(Map<String, Object> body)
            throws StorageException, TachographException {

        long deviceId = toLong(body.get("deviceId"));
        String downloadType = body.get("downloadType") != null
                ? body.get("downloadType").toString() : TachographDownloadJob.TYPE_VEHICLE;

        permissionsService.checkPermission(Device.class, getUserId(), deviceId);

        TachographDownloadJob job = tachographManager.createDownloadJob(
                deviceId, downloadType, getUserId(),
                parseDate(body.get("from")), parseDate(body.get("to")));
        return Response.status(Response.Status.ACCEPTED).entity(job).build();
    }

    @GET
    @Path("downloads")
    public List<TachographDownloadJob> listDownloads(
            @QueryParam("deviceId") Long deviceId,
            @QueryParam("status") String status,
            @QueryParam("from") String from,
            @QueryParam("to") String to,
            @QueryParam("limit") Integer limit) throws StorageException {

        if (deviceId != null) {
            permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        }
        return tachographManager.getJobs(
                getUserId(), isAdministrator(), deviceId, status,
                parseDate(from), parseDate(to), limit != null ? limit : 100);
    }

    @GET
    @Path("downloads/{id}")
    public TachographDownloadJob getDownload(@PathParam("id") long id)
            throws StorageException, TachographException {
        TachographDownloadJob job = tachographManager.getJob(id);
        if (job == null) {
            throw new TachographException("TACHO_NOT_FOUND", "Job not found: " + id);
        }
        permissionsService.checkPermission(Device.class, getUserId(), job.getDeviceId());
        return job;
    }

    @POST
    @Path("downloads/{id}/cancel")
    public Response cancelDownload(@PathParam("id") long id)
            throws StorageException, TachographException {
        TachographDownloadJob job = tachographManager.getJob(id);
        if (job == null) {
            throw new TachographException("TACHO_NOT_FOUND", "Job not found: " + id);
        }
        permissionsService.checkPermission(Device.class, getUserId(), job.getDeviceId());
        tachographManager.cancelJob(id, getUserId());
        return Response.noContent().build();
    }

    // -----------------------------------------------------------------------
    // Files
    // -----------------------------------------------------------------------

    @GET
    @Path("files")
    public List<TachographFile> listFiles(
            @QueryParam("deviceId") Long deviceId,
            @QueryParam("type") String fileType,
            @QueryParam("limit") Integer limit) throws StorageException {

        if (deviceId != null) {
            permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        }
        return tachographManager.getFiles(
                getUserId(), isAdministrator(), deviceId, fileType, limit != null ? limit : 100);
    }

    /**
     * Streams a stored DDD file.
     *
     * <p>The retrieval is audited, because handing someone a driver's complete working record is
     * exactly the event a data protection audit asks about. The response carries the digest so a
     * recipient can confirm the bytes are the ones the vehicle produced.
     */
    @GET
    @Path("files/{id}/download")
    @Produces(MediaType.APPLICATION_OCTET_STREAM)
    public Response downloadFile(@PathParam("id") long fileId)
            throws StorageException, TachographException, IOException {

        TachographFile file = tachographManager.getFile(fileId);
        if (file == null) {
            throw new TachographException("TACHO_NOT_FOUND", "File not found: " + fileId);
        }
        permissionsService.checkPermission(Device.class, getUserId(), file.getDeviceId());

        java.nio.file.Path path = java.nio.file.Path.of(file.getStoragePath());
        if (!Files.exists(path)) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_STORAGE,
                    "The stored file is missing from disk: " + file.getFileName());
        }

        auditService.record(getUserId(), file.getDeviceId(),
                TachographAudit.ACTION_FILE_RETRIEVED, "File " + file.getFileName() + " downloaded");

        StreamingOutput output = out -> {
            try (InputStream in = Files.newInputStream(path)) {
                in.transferTo(out);
            }
        };

        String safeName = file.getFileName().replaceAll("[^A-Za-z0-9._-]", "_");
        return Response.ok(output, MediaType.APPLICATION_OCTET_STREAM)
                .header("Content-Disposition", "attachment; filename=\"" + safeName + "\"")
                .header("Content-Length", file.getFileSize())
                .header("X-File-SHA256", file.getSha256() != null ? file.getSha256() : "")
                .build();
    }

    @DELETE
    @Path("files/{id}")
    public Response deleteFile(@PathParam("id") long fileId)
            throws StorageException, TachographException {
        TachographFile file = tachographManager.getFile(fileId);
        if (file == null) {
            return Response.noContent().build();
        }
        permissionsService.checkAdmin(getUserId());
        tachographManager.deleteFile(fileId, getUserId());
        return Response.noContent().build();
    }

    // -----------------------------------------------------------------------
    // Bridges, operator side
    // -----------------------------------------------------------------------

    @GET
    @Path("bridges")
    public List<TachographBridge> listBridges() throws StorageException {
        return bridgeManager.list(getUserId(), isAdministrator());
    }

    @POST
    @Path("bridges/pairing-code")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> generatePairingCode(Map<String, Object> body) throws StorageException {
        long groupId = toLong(body.get("groupId"));
        String name = body.get("name") != null ? body.get("name").toString() : "Tacho Bridge";

        if (groupId != 0) {
            permissionsService.checkPermission(Group.class, getUserId(), groupId);
        } else {
            permissionsService.checkAdmin(getUserId());
        }

        TachographBridge bridge = bridgeManager.createPairingCode(groupId, name, getUserId());
        return Map.of(
                "id", bridge.getId(),
                "pairingCode", bridge.getPairingCode(),
                "expiresAt", bridge.getPairingCodeExpiresAt().getTime(),
                "name", bridge.getName());
    }

    @GET
    @Path("bridges/{id}")
    public TachographBridge getBridge(@PathParam("id") long id)
            throws StorageException, TachographException {
        TachographBridge bridge = requireVisibleBridge(id);
        return bridge;
    }

    @DELETE
    @Path("bridges/{id}")
    public Response deleteBridge(@PathParam("id") long id)
            throws StorageException, TachographException {
        requireVisibleBridge(id);
        bridgeManager.delete(id, getUserId());
        return Response.noContent().build();
    }

    /** Reads the company card's identity so an operator can confirm the right card is fitted. */
    @POST
    @Path("bridges/{id}/read-card")
    public CardIdentity readCard(@PathParam("id") long id)
            throws StorageException, TachographException {
        requireVisibleBridge(id);
        return bridgeManager.readCardIdentity(id, getUserId());
    }

    // -----------------------------------------------------------------------
    // Bridges, bridge side: authenticated by token, never by user session
    // -----------------------------------------------------------------------

    /**
     * A bridge exchanges its one-time pairing code for a token.
     *
     * <p>Open to unauthenticated callers because a bridge has no user session and nothing to
     * authenticate with yet — the pairing code is the credential. The code is single use,
     * expires in fifteen minutes, and is only ever compared as a hash, so an attacker would need
     * to guess one of a million values inside that window and beat the operator to it.
     */
    @PermitAll
    @POST
    @Path("bridges/register")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> registerBridge(Map<String, Object> body)
            throws StorageException, TachographException {

        TachographBridge bridge = bridgeManager.register(
                asString(body.get("pairingCode")),
                asString(body.get("bridgeId")),
                asString(body.get("name")),
                asString(body.get("softwareVersion")),
                asString(body.get("hostname")));

        // The token is returned exactly once, here. It is stored only as a hash.
        return Map.of(
                "id", bridge.getId(),
                "bridgeId", bridge.getBridgeId(),
                "bridgeToken", bridge.getBridgeToken(),
                "name", bridge.getName(),
                "groupId", bridge.getGroupId());
    }

    /** Reports a bridge's reader and card state. Authenticated by the bridge token. */
    @PermitAll
    @POST
    @Path("bridges/{id}/heartbeat")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> heartbeat(@PathParam("id") long id, Map<String, Object> body)
            throws StorageException {
        TachographBridge bridge = authenticateBridge(id);
        return bridgeManager.heartbeat(bridge, body);
    }

    /**
     * Long-polls for the next card command a bridge should run.
     *
     * <p>Command and response bytes travel as base64. They are the card's own protocol data and
     * the server does not interpret them; it only carries them between the vehicle unit and the
     * reader.
     */
    @PermitAll
    @GET
    @Path("bridges/{id}/card/poll")
    public Map<String, Object> pollCard(@PathParam("id") long id) throws StorageException {

        authenticateBridge(id);

        CardCommand command = cardService.poll(id, config.getInteger(Keys.TACHO_CARD_POLL_TIMEOUT));
        if (command == null) {
            return Map.of("command", "NONE");
        }
        return Map.of(
                "command", command.getType(),
                "commandId", command.getId(),
                "data", Base64.getEncoder().encodeToString(command.getRequest()));
    }

    @PermitAll
    @POST
    @Path("bridges/{id}/card/respond")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> respondCard(@PathParam("id") long id, Map<String, Object> body)
            throws StorageException {

        authenticateBridge(id);

        String commandId = asString(body.get("commandId"));
        if (commandId == null) {
            return Map.of("accepted", false, "reason", "commandId is required");
        }

        String errorCode = asString(body.get("errorCode"));
        CardResponse response;
        if (errorCode != null) {
            response = CardResponse.failure(errorCode, asString(body.get("errorMessage")));
        } else {
            String data = asString(body.get("data"));
            response = CardResponse.success(
                    data != null ? Base64.getDecoder().decode(data) : new byte[0]);
        }

        boolean accepted = cardService.complete(id, commandId, response);
        return Map.of("accepted", accepted);
    }

    // -----------------------------------------------------------------------
    // Delivery to analysis bureaux
    // -----------------------------------------------------------------------

    @GET
    @Path("targets")
    public List<TachographForwardTarget> listTargets() throws StorageException {
        return forwardService.listTargets(getUserId(), isAdministrator());
    }

    @POST
    @Path("targets")
    @Consumes(MediaType.APPLICATION_JSON)
    public TachographForwardTarget createTarget(TachographForwardTarget target)
            throws StorageException {
        permissionsService.checkAdmin(getUserId());
        target.setId(0);
        return forwardService.saveTarget(target, getUserId());
    }

    @PUT
    @Path("targets/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public TachographForwardTarget updateTarget(
            @PathParam("id") long id, TachographForwardTarget target) throws StorageException {
        permissionsService.checkAdmin(getUserId());
        target.setId(id);
        return forwardService.saveTarget(target, getUserId());
    }

    @DELETE
    @Path("targets/{id}")
    public Response deleteTarget(@PathParam("id") long id) throws StorageException {
        permissionsService.checkAdmin(getUserId());
        forwardService.deleteTarget(id, getUserId());
        return Response.noContent().build();
    }

    /** Checks a bureau is reachable and the stored credential works. */
    @POST
    @Path("targets/{id}/test")
    public Map<String, Object> testTarget(@PathParam("id") long id) throws StorageException {
        try {
            permissionsService.checkAdmin(getUserId());
            forwardService.testTarget(id, getUserId());
            return Map.of("success", true, "message", "Connection succeeded");
        } catch (ForwardException e) {
            return Map.of(
                    "success", false,
                    "errorCode", e.getErrorCode(),
                    "message", String.valueOf(e.getMessage()),
                    "retryable", e.isRetryable());
        }
    }

    @GET
    @Path("forwards")
    public List<TachographForward> listForwards(
            @QueryParam("fileId") Long fileId,
            @QueryParam("status") String status,
            @QueryParam("limit") Integer limit) throws StorageException {
        return forwardService.listForwards(fileId, status, limit != null ? limit : 100);
    }

    @POST
    @Path("forwards/{id}/retry")
    public Response retryForward(@PathParam("id") long id) throws StorageException {
        permissionsService.checkAdmin(getUserId());
        forwardService.retry(id, getUserId());
        return Response.noContent().build();
    }

    // -----------------------------------------------------------------------
    // Audit
    // -----------------------------------------------------------------------

    @GET
    @Path("audit")
    public List<TachographAudit> listAudit(
            @QueryParam("deviceId") Long deviceId,
            @QueryParam("limit") Integer limit) throws StorageException {

        if (deviceId != null) {
            permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        } else {
            permissionsService.checkAdmin(getUserId());
        }
        return auditService.list(deviceId, limit != null ? limit : 200);
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private boolean isAdministrator() throws StorageException {
        return !permissionsService.notAdmin(getUserId());
    }

    /** Loads a bridge and checks the caller may see the group it belongs to. */
    private TachographBridge requireVisibleBridge(long id)
            throws StorageException, TachographException {
        TachographBridge bridge = bridgeManager.get(id);
        if (bridge == null) {
            throw new TachographException("TACHO_NOT_FOUND", "Bridge not found: " + id);
        }
        if (bridge.getGroupId() != 0) {
            permissionsService.checkPermission(Group.class, getUserId(), bridge.getGroupId());
        } else {
            permissionsService.checkAdmin(getUserId());
        }
        return bridge;
    }

    /**
     * Authenticates a bridge from its token header.
     *
     * <p>These endpoints carry {@code @PermitAll} so they bypass the user-session filter, which
     * makes this the only thing standing between an anonymous caller and a company card. A
     * failure is answered with a bare 401 and no detail: a caller who does not hold the token
     * learns nothing about whether the bridge exists.
     */
    private TachographBridge authenticateBridge(long id) throws StorageException {
        try {
            return bridgeManager.authenticate(id, getBridgeToken());
        } catch (TachographException e) {
            throw new jakarta.ws.rs.WebApplicationException(
                    Response.status(Response.Status.UNAUTHORIZED).build());
        }
    }

    private String getBridgeToken() {
        String token = request.getHeader("X-Bridge-Token");
        if (token == null) {
            String authorization = request.getHeader("Authorization");
            if (authorization != null && authorization.startsWith("Bearer ")) {
                token = authorization.substring("Bearer ".length());
            }
        }
        return token;
    }

    private String asString(Object value) {
        if (value == null) {
            return null;
        }
        String text = value.toString().trim();
        return text.isEmpty() ? null : text;
    }

    private long toLong(Object value) {
        if (value == null) {
            return 0;
        }
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.parseLong(value.toString());
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    /** Accepts either epoch milliseconds or an ISO-8601 instant. */
    private Date parseDate(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number number) {
            return new Date(number.longValue());
        }
        String text = value.toString().trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return new Date(Long.parseLong(text));
        } catch (NumberFormatException e) {
            try {
                return Date.from(Instant.parse(text));
            } catch (DateTimeParseException ex) {
                return null;
            }
        }
    }
}
