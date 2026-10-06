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
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.StreamingOutput;
import org.traccar.api.BaseResource;
import org.traccar.media.Cmsv9Manager;
import org.traccar.model.Device;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;

import java.io.IOException;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.Map;

@Path("cmsv9")
@Produces(MediaType.APPLICATION_JSON)
public class Cmsv9Resource extends BaseResource {

    @Inject
    private Cmsv9Manager cmsv9Manager;

    @GET
    @Path("config")
    public Map<String, Object> config(@QueryParam("deviceId") Long deviceId) throws Exception {
        if (!cmsv9Manager.isConfigured()) {
            return Map.of("configured", false);
        }
        cmsv9Manager.login();
        int channels = cmsv9Manager.getChannels();
        if (deviceId != null) {
            try {
                String terminal = getCmsDeviceId(deviceId);
                int deviceChannels = cmsv9Manager.getDeviceChannels(terminal);
                if (deviceChannels > 0) {
                    channels = deviceChannels;
                }
            } catch (Exception e) {
                // fall back to configured default
            }
        }
        return Map.of(
                "configured", true,
                "mediaPort", cmsv9Manager.getMediaPort(),
                "channels", channels);
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
            @PathParam("channel") int channel,
            @QueryParam("stream") @DefaultValue("1") int streamType) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;

        cmsv9Manager.playLiveAsync(terminal, cnmsChannel, streamType);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("errCode", 0);
        result.put("flvUrl", cmsv9Manager.buildLiveFlvUrl(terminal, cnmsChannel));
        result.put("terminal", terminal);
        result.put("channel", channel);
        return result;
    }

    @GET
    @Path("stream-status/{deviceId}/{channel}")
    public Map<String, Object> streamStatus(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;
        String streamName = cmsv9Manager.liveStreamName(terminal, cnmsChannel);
        return Map.of("ready", cmsv9Manager.isStreamLive(streamName));
    }

    /**
     * Proxies the live FLV stream from the local ZLMediaKit. Returns 404
     * when the stream is not live yet (checked via the media API, so no
     * CNMS on-demand hooks are triggered).
     */
    @GET
    @Path("stream/{deviceId}/{channel}")
    public Response stream(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;
        String streamName = cmsv9Manager.liveStreamName(terminal, cnmsChannel);

        if (!cmsv9Manager.isStreamLive(streamName)) {
            return Response.status(Response.Status.NOT_FOUND).build();
        }
        InputStream input = cmsv9Manager.openStream(streamName);
        if (input == null) {
            return Response.status(Response.Status.NOT_FOUND).build();
        }

        StreamingOutput output = out -> {
            try (InputStream in = input) {
                byte[] buffer = new byte[8192];
                int length;
                while ((length = in.read(buffer)) != -1) {
                    out.write(buffer, 0, length);
                    out.flush();
                }
            } catch (IOException e) {
                // client disconnected or stream ended
            }
        };
        return Response.ok(output)
                .header("Content-Type", "video/x-flv")
                .header("Cache-Control", "no-cache")
                .build();
    }

    /**
     * On-demand footage download. Triggers a playback of the requested time
     * range on the device, then streams the resulting FLV straight through to
     * the client as a file attachment. The bytes are piped, never written to
     * disk, so there is no server-side storage cost. Requires the device to be
     * online (it plays the clip back from its SD card in real time).
     */
    @GET
    @Path("download/{deviceId}/{channel}")
    public Response download(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel,
            @QueryParam("startTime") String startTime,
            @QueryParam("endTime") String endTime,
            @QueryParam("format") String format) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;
        boolean mp4 = cmsv9Manager.isFfmpegAvailable();
        // "share" re-encodes to H.264 with the index at the front, which is
        // what a phone or WhatsApp will accept; the default streams the
        // camera's own H.265 straight through, which starts instantly and is
        // what the review player scrubs through.
        boolean shareable = mp4 && "share".equalsIgnoreCase(format);
        InputStream input;
        if (shareable) {
            input = cmsv9Manager.openPlaybackShareableMp4(terminal, cnmsChannel, startTime, endTime);
        } else if (mp4) {
            input = cmsv9Manager.openPlaybackMp4(terminal, cnmsChannel, startTime, endTime);
        } else {
            input = cmsv9Manager.openPlaybackStream(terminal, cnmsChannel, startTime, endTime);
        }
        if (input == null) {
            return Response.status(Response.Status.NOT_FOUND).build();
        }

        String stamp = startTime != null ? startTime.replaceAll("[^0-9]", "") : "clip";
        String filename = terminal + "_ch" + cnmsChannel + "_" + stamp + (mp4 ? ".mp4" : ".flv");

        StreamingOutput output = out -> {
            try (InputStream in = input) {
                byte[] buffer = new byte[8192];
                int length;
                while ((length = in.read(buffer)) != -1) {
                    out.write(buffer, 0, length);
                    out.flush();
                }
            } catch (IOException e) {
                // client disconnected or playback stream ended
            }
        };
        return Response.ok(output)
                .header("Content-Type", mp4 ? "video/mp4" : "video/x-flv")
                .header("Content-Disposition", "attachment; filename=\"" + filename + "\"")
                .header("Cache-Control", "no-cache")
                .build();
    }


    /**
     * Wakes a camera's own settings page and says where it will appear.
     *
     * <p>Two steps, and the first one is the one that matters: the camera is
     * told to dial out and open a tunnel, and only then does the address mean
     * anything. Opening the address on its own - which is what this used to do -
     * reaches a proxy with nothing registered behind it and answers 404.
     *
     * <p>The camera takes some seconds to bring the tunnel up, so the caller is
     * told how long to wait rather than being left to guess. It must be online:
     * this is a live order, not a stored setting.
     */
    @POST
    @Path("device-web/{deviceId}")
    public Map<String, Object> deviceWeb(@PathParam("deviceId") long deviceId) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("url", cmsv9Manager.deviceWebUrl(terminal));
        result.put("waitSeconds", 20);

        // Asked first, because an offline camera cannot answer and the caller
        // would otherwise wait the full twenty seconds only to meet a 404 that
        // says nothing about why. A vehicle parked with the ignition off is
        // still online; only a camera CNMS cannot see at all is refused, and an
        // unreadable status is not treated as offline.
        if (Boolean.FALSE.equals(cmsv9Manager.isDeviceOnline(terminal))) {
            result.put("sent", false);
            result.put("detail", "This camera is offline, so it cannot open its settings page. "
                    + "It has to be powered up and connected before this will work.");
            return result;
        }

        boolean sent = cmsv9Manager.wsOpenDeviceWeb(terminal);
        result.put("sent", sent);
        if (!sent) {
            result.put("detail", "The camera did not acknowledge the request. Try again in a moment.");
        }
        return result;
    }

    @POST
    @Path("stop/{deviceId}/{channel}")
    public Map<String, Object> stop(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel) throws Exception {
        String terminal = getCmsDeviceId(deviceId);
        int cnmsChannel = channel + 1;

        cmsv9Manager.stopLiveAsync(terminal, cnmsChannel);
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

        JsonNode resp = cmsv9Manager.playbackAppoint(
                terminal, String.valueOf(cnmsChannel), startTime, endTime);
        String flvUrl = resp.path("resultData").path("httpurl").asText("");
        if (flvUrl.isEmpty()) {
            flvUrl = cmsv9Manager.buildPlaybackFlvUrl(terminal, cnmsChannel);
        }

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
