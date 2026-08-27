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
import org.traccar.model.TachographFile;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;
import org.traccar.tachograph.TachographException;
import org.traccar.tachograph.TachographManager;
import org.traccar.tachograph.TachographStorage;

import jakarta.servlet.http.HttpServletRequest;

import java.io.IOException;
import java.io.InputStream;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Path("tachograph")
@Produces(MediaType.APPLICATION_JSON)
public class TachographResource extends BaseResource {

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
    // Downloads
    // -----------------------------------------------------------------------

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
