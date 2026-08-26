/*
 * Copyright 2026 DH FleetView contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package org.traccar.api.resource;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import org.traccar.api.BaseResource;
import org.traccar.media.Cmsv9Manager;
import org.traccar.model.Device;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;

import java.util.LinkedHashMap;
import java.util.Map;

@Path("cmsv9")
@Produces(MediaType.APPLICATION_JSON)
public class Cmsv9Resource extends BaseResource {

    @Inject
    private Cmsv9Manager cmsv9Manager;

    @GET
    @Path("config")
    public Map<String, Object> config() throws Exception {
        if (!cmsv9Manager.isConfigured()) {
            return Map.of("configured", false);
        }
        cmsv9Manager.login();
        return Map.of(
                "configured", true,
                "mediaPort", cmsv9Manager.getMediaPort(),
                "channels", cmsv9Manager.getChannels());
    }

    @GET
    @Path("vehicles")
    public JsonNode vehicles() throws Exception {
        return cmsv9Manager.deptTree();
    }

    @POST
    @Path("live/{deviceId}/{channel}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> live(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;

        cmsv9Manager.wsPlay(terminal, cnmsChannel);
        String flvUrl = cmsv9Manager.buildLiveFlvUrl(terminal, cnmsChannel);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("errCode", 0);
        result.put("flvUrl", flvUrl);
        result.put("terminal", terminal);
        result.put("channel", channel);
        return result;
    }

    @POST
    @Path("stop/{deviceId}/{channel}")
    public Map<String, Object> stop(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;

        cmsv9Manager.wsStop(terminal, cnmsChannel);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("errCode", 0);
        result.put("resultMsg", "stopped");
        return result;
    }

    @POST
    @Path("playback/{deviceId}/{channel}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> playback(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel,
            Map<String, String> params) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;
        String startTime = params.get("startTime");
        String endTime = params.get("endTime");

        cmsv9Manager.wsPlayback(terminal, cnmsChannel, startTime, endTime);
        String flvUrl = cmsv9Manager.buildPlaybackFlvUrl(terminal, cnmsChannel);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("errCode", 0);
        result.put("flvUrl", flvUrl);
        result.put("terminal", terminal);
        result.put("channel", channel);
        return result;
    }

    @GET
    @Path("history/{deviceId}/{channel}")
    public JsonNode history(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel,
            @QueryParam("from") String from,
            @QueryParam("to") String to) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;
        return cmsv9Manager.queryTerminalFileList(
                terminal, String.valueOf(cnmsChannel), from, to);
    }

    @GET
    @Path("search")
    public JsonNode search(
            @QueryParam("deviceId") long deviceId,
            @QueryParam("channel") int channel,
            @QueryParam("from") String from,
            @QueryParam("to") String to,
            @QueryParam("type") String type) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;
        return cmsv9Manager.getDownVideosAndPictures(
                terminal, from, to, type != null ? type : "1");
    }

    private String getCmsDeviceId(long deviceId) throws StorageException {
        permissionsService.checkPermission(Device.class, getUserId(), deviceId);
        Device device = storage.getObject(Device.class, new Request(
                new Columns.All(), new Condition.Equals("id", deviceId)));
        if (device == null) {
            throw new IllegalArgumentException("Device not found");
        }
        String cmsDeviceId = device.getString("cmsv9DeviceId");
        if (cmsDeviceId == null || cmsDeviceId.isBlank()) {
            throw new IllegalArgumentException("CMSV9 device ID is not configured");
        }
        return cmsDeviceId;
    }
}
