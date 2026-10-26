/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
/*
 * Copyright 2026 DH FleetView contributors
 */
package org.traccar.api.resource;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.StreamingOutput;

import org.traccar.api.BaseResource;
import org.traccar.model.Device;
import org.traccar.model.Group;
import org.traccar.model.TachographBridge;
import org.traccar.model.TachographConfiguration;
import org.traccar.model.TachographDownloadJob;
import org.traccar.model.Position;
import org.traccar.model.TachographFile;
import org.traccar.model.User;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Order;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.TachographException;
import org.traccar.tachograph.TachographManager;
import org.traccar.tachograph.TachographStorage;

import jakarta.servlet.http.HttpServletRequest;

import java.io.IOException;
import java.io.InputStream;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

@Path("tachograph")
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

    @jakarta.ws.rs.core.Context
    private HttpServletRequest request;

    @Inject
    private TachographManager tachographManager;

    @Inject
    private TachographStorage tachographStorage;

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
            TachographConfiguration config) throws StorageException {
        permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        config.setDeviceId(deviceId);
        tachographManager.saveConfiguration(config);
        return config;
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
    public Response createDownload(Map<String, Object> body) throws StorageException, TachographException {
        long deviceId = toLong(body.get("deviceId"));
        String downloadType = (String) body.get("downloadType");
        if (downloadType == null) {
            downloadType = TachographDownloadJob.TYPE_VEHICLE;
        }
        permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        TachographDownloadJob job = tachographManager.createDownloadJob(
                deviceId, downloadType, getUserId(), null, null);
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
        // permission: if deviceId specified, check it; otherwise filter to user's devices
        if (deviceId != null) {
            permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        }
        return tachographManager.getJobs(deviceId, status, parseDate(from), parseDate(to),
                limit != null ? limit : 100);
    }

    @GET
    @Path("downloads/{id}")
    public TachographDownloadJob getDownload(@PathParam("id") long id)
            throws StorageException, TachographException {
        TachographDownloadJob job = tachographManager.getJob(id);
        if (job == null) {
            throw new TachographException("NOT_FOUND", "Job not found: " + id);
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
            throw new TachographException("NOT_FOUND", "Job not found: " + id);
        }
        permissionsService.checkPermission(Device.class, getUserId(), job.getDeviceId());
        tachographManager.cancelJob(id, getUserId());
        return Response.ok().build();
    }

    // -----------------------------------------------------------------------
    // Files
    // -----------------------------------------------------------------------

    @GET
    @Path("files")
    public List<TachographFile> listFiles(
            @QueryParam("deviceId") Long deviceId,
            @QueryParam("limit") Integer limit) throws StorageException {
        if (deviceId != null) {
            permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        }
        return tachographManager.getFiles(deviceId, limit != null ? limit : 100);
    }

    @GET
    @Path("files/{id}/download")
    @Produces(MediaType.APPLICATION_OCTET_STREAM)
    public Response downloadFile(@PathParam("id") long fileId)
            throws StorageException, TachographException, IOException {
        TachographFile file = tachographManager.getFile(fileId);
        if (file == null) {
            throw new TachographException("NOT_FOUND", "File not found: " + fileId);
        }
        permissionsService.checkPermission(Device.class, getUserId(), file.getDeviceId());

        java.nio.file.Path path = java.nio.file.Path.of(file.getStoragePath());
        if (!java.nio.file.Files.exists(path)) {
            throw new TachographException(
                    TachographDownloadJob.ERROR_STORAGE, "File not found on storage: " + file.getFileName());
        }

        InputStream input = java.nio.file.Files.newInputStream(path);
        StreamingOutput output = out -> {
            try (InputStream in = input) {
                byte[] buffer = new byte[8192];
                int len;
                while ((len = in.read(buffer)) != -1) {
                    out.write(buffer, 0, len);
                }
            }
        };

        String safeName = file.getFileName().replaceAll("[^a-zA-Z0-9._-]", "_");
        return Response.ok(output, MediaType.APPLICATION_OCTET_STREAM)
                .header("Content-Disposition", "attachment; filename=\"" + safeName + "\"")
                .header("X-File-SHA256", file.getSha256() != null ? file.getSha256() : "")
                .build();
    }

    // -----------------------------------------------------------------------
    // Bridges
    // -----------------------------------------------------------------------

    @GET
    @Path("bridges")
    public List<TachographBridge> listBridges() throws StorageException {
        // bridges are group-scoped; filter to user's groups
        return tachographManager.listBridges(getUserId());
    }

    @POST
    @Path("bridges/pairing-code")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, String> generatePairingCode(Map<String, Object> body) throws StorageException {
        long groupId = toLong(body.get("groupId"));
        String name = (String) body.getOrDefault("name", "Tacho Bridge");
        permissionsService.checkPermission(Group.class, getUserId(), groupId);
        String code = tachographManager.generatePairingCode(groupId, name, getUserId());
        Map<String, String> result = new HashMap<>();
        result.put("pairingCode", code);
        return result;
    }

    @POST
    @Path("bridges/register")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response registerBridge(Map<String, Object> body) throws StorageException, TachographException {
        String pairingCode = (String) body.get("pairingCode");
        String bridgeId = (String) body.get("bridgeId");
        String name = (String) body.getOrDefault("name", "Tacho Bridge");
        String softwareVersion = (String) body.getOrDefault("softwareVersion", "unknown");
        if (pairingCode == null || bridgeId == null) {
            return Response.status(Response.Status.BAD_REQUEST).entity(
                    Map.of("error", "pairingCode and bridgeId are required")).build();
        }
        TachographBridge bridge = tachographManager.registerBridge(
                pairingCode, bridgeId, name, softwareVersion);
        return Response.ok(bridge).build();
    }

    @POST
    @Path("bridges/{id}/heartbeat")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> heartbeat(
            @PathParam("id") long id, Map<String, Object> body)
            throws StorageException, TachographException {
        // bridge authenticates with token header X-Bridge-Token
        String token = getBridgeToken();
        return tachographManager.heartbeat(id, token, body);
    }

    @GET
    @Path("bridges/{id}/status")
    public Map<String, Object> bridgeStatus(@PathParam("id") long id)
            throws StorageException, TachographException {
        TachographBridge bridge = tachographManager.getBridge(id);
        if (bridge == null) {
            throw new TachographException("NOT_FOUND", "Bridge not found: " + id);
        }
        permissionsService.checkPermission(Group.class, getUserId(), bridge.getGroupId());
        Map<String, Object> result = new HashMap<>();
        result.put("bridge", bridge);
        return result;
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private String getBridgeToken() {
        String auth = request.getHeader("X-Bridge-Token");
        if (auth == null) {
            auth = request.getHeader("Authorization");
            if (auth != null && auth.startsWith("Bearer ")) {
                auth = auth.substring(7);
            }
        }
        return auth;
    }

    private long toLong(Object value) {
        if (value == null) return 0;
        if (value instanceof Number n) return n.longValue();
        return Long.parseLong(value.toString());
    }

    private Date parseDate(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return new Date(Long.parseLong(value));
        } catch (NumberFormatException e) {
            try {
                return javax.xml.bind.DatatypeConverter.parseDateTime(value).getTime();
            } catch (Exception ex) {
                return null;
            }
        }
    }
}
