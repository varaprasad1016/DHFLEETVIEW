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
import jakarta.ws.rs.BadRequestException;
import jakarta.ws.rs.HeaderParam;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.api.BaseResource;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.media.Cmsv9ClipStore;
import org.traccar.media.Cmsv9Manager;
import org.traccar.model.Device;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.util.LinkedHashMap;
import java.util.Map;


@Path("cmsv9")
@Produces(MediaType.APPLICATION_JSON)
public class Cmsv9Resource extends BaseResource {

    private static final Logger LOG = LoggerFactory.getLogger(Cmsv9Resource.class);

    @Inject
    private Cmsv9Manager cmsv9Manager;

    @Inject
    private Cmsv9ClipStore clipStore;

    @Inject
    private Config config;

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
     * Asks for a clip to be fetched off the vehicle, without waiting for it.
     *
     * <p>Fetching is not quick and it is not free: the camera plays the footage
     * back off its own card in real time over the vehicle's mobile connection,
     * so ten minutes of footage takes ten minutes and costs about 220 MB. The
     * caller gets told what it will cost and then polls {@link #clipStatus}.
     */
    @POST
    @Path("clip/{deviceId}/{channel}")
    public Map<String, Object> prepareClip(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel,
            @QueryParam("startTime") String startTime,
            @QueryParam("endTime") String endTime,
            @QueryParam("format") String format) throws Exception {
        Cmsv9ClipStore.Clip clip = clipOf(deviceId, channel, startTime, endTime, format);
        int seconds = Cmsv9ClipStore.seconds(clip);
        int maxMinutes = config.getInteger(Keys.CMSV9_CLIP_MAX_MINUTES);
        if (seconds <= 0) {
            throw new BadRequestException("That is not a valid time range.");
        }
        if (seconds > maxMinutes * 60) {
            throw new BadRequestException(
                    "That clip is longer than " + maxMinutes + " minutes. The camera plays footage back in real time"
                    + " over the vehicle's mobile data, so please ask for a shorter piece.");
        }
        Map<String, Object> result = new LinkedHashMap<>(clipState(clip));
        if (!Boolean.TRUE.equals(result.get("ready"))) {
            clipStore.request(clip);
            result = new LinkedHashMap<>(clipState(clip));
        }
        return result;
    }

    /** How far along a clip is: cached already, being fetched, or neither. */
    @GET
    @Path("clip/{deviceId}/{channel}")
    public Map<String, Object> clipStatus(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel,
            @QueryParam("startTime") String startTime,
            @QueryParam("endTime") String endTime,
            @QueryParam("format") String format) throws Exception {
        return clipState(clipOf(deviceId, channel, startTime, endTime, format));
    }

    private Cmsv9ClipStore.Clip clipOf(
            long deviceId, int channel, String startTime, String endTime, String format) throws Exception {
        return new Cmsv9ClipStore.Clip(
                getCmsDeviceId(deviceId), channel + 1, startTime, endTime,
                cmsv9Manager.isFfmpegAvailable() && "share".equalsIgnoreCase(format));
    }

    private Map<String, Object> clipState(Cmsv9ClipStore.Clip clip) throws IOException {
        Map<String, Object> result = new LinkedHashMap<>();
        int seconds = Cmsv9ClipStore.seconds(clip);
        result.put("seconds", seconds);
        result.put("estimatedBytes", seconds * Cmsv9ClipStore.BYTES_PER_MINUTE / 60);
        java.nio.file.Path file = clipStore.existing(clip);
        if (file != null) {
            result.put("ready", true);
            result.put("bytes", Files.size(file));
            return result;
        }
        result.put("ready", false);
        Cmsv9ClipStore.Capture capture = clipStore.running(clip);
        if (capture != null) {
            result.put("working", true);
            result.put("bytes", capture.getBytes());
            result.put("elapsedSeconds", capture.getElapsedSeconds());
        } else {
            result.put("working", false);
        }
        return result;
    }

    /**
     * Serves a clip off the disk cache.
     *
     * <p>Nothing streams through from the vehicle any more. A clip that has not
     * been fetched yet is fetched now and the request waits for it, but a clip
     * already held is served straight from the file - with a length and byte
     * ranges, so the browser can seek in it and a download manager asking a
     * second time costs the vehicle nothing. That second ask is what used to
     * take the playback stream away from the first one and leave both with a
     * few seconds of footage.
     */
    @GET
    @Path("download/{deviceId}/{channel}")
    public Response download(
            @PathParam("deviceId") long deviceId,
            @PathParam("channel") int channel,
            @QueryParam("startTime") String startTime,
            @QueryParam("endTime") String endTime,
            @QueryParam("format") String format,
            @QueryParam("disposition") String disposition,
            @HeaderParam("Range") String range) throws Exception {
        Cmsv9ClipStore.Clip clip = clipOf(deviceId, channel, startTime, endTime, format);
        int seconds = Cmsv9ClipStore.seconds(clip);
        int maxMinutes = config.getInteger(Keys.CMSV9_CLIP_MAX_MINUTES);
        if (seconds <= 0 || seconds > maxMinutes * 60) {
            return Response.status(Response.Status.BAD_REQUEST).build();
        }
        java.nio.file.Path file;
        try {
            // Short clips are worth waiting for inline. A long one would hold
            // this thread for its own length and be cut off by the proxy long
            // before it finished, so the capture carries on in the background
            // and the caller is told to come back - which is what the video
            // page does anyway, having asked for the clip first.
            file = clipStore.request(clip).get(45, java.util.concurrent.TimeUnit.SECONDS);
        } catch (java.util.concurrent.TimeoutException e) {
            return Response.status(Response.Status.SERVICE_UNAVAILABLE)
                    .header("Retry-After", Math.max(5, seconds / 4))
                    .entity(Map.of(
                            "message", "That footage is still coming off the vehicle.",
                            "seconds", seconds))
                    .type(MediaType.APPLICATION_JSON)
                    .build();
        } catch (java.util.concurrent.ExecutionException e) {
            LOG.warn("Clip could not be fetched: {}", e.getCause().getMessage());
            return Response.status(Response.Status.NOT_FOUND).build();
        }

        long length = Files.size(file);
        String filename = file.getFileName().toString();
        Response.ResponseBuilder builder;
        long from = 0;
        long to = length - 1;

        // One range, which is all a browser ever asks a video for.
        if (range != null && range.startsWith("bytes=") && !range.contains(",")) {
            String[] parts = range.substring(6).split("-", 2);
            try {
                if (parts[0].isEmpty()) {
                    from = Math.max(0, length - Long.parseLong(parts[1]));
                } else {
                    from = Long.parseLong(parts[0]);
                    if (parts.length > 1 && !parts[1].isEmpty()) {
                        to = Math.min(to, Long.parseLong(parts[1]));
                    }
                }
            } catch (NumberFormatException e) {
                from = 0;
                to = length - 1;
            }
            if (from > to || from >= length) {
                return Response.status(416).header("Content-Range", "bytes */" + length).build();
            }
            builder = Response.status(Response.Status.PARTIAL_CONTENT)
                    .header("Content-Range", "bytes " + from + "-" + to + "/" + length);
        } else {
            builder = Response.ok();
        }

        final long start = from;
        final long count = to - from + 1;
        StreamingOutput output = out -> {
            try (InputStream in = Files.newInputStream(file)) {
                in.skipNBytes(start);
                byte[] buffer = new byte[64 * 1024];
                long left = count;
                while (left > 0) {
                    int read = in.read(buffer, 0, (int) Math.min(buffer.length, left));
                    if (read < 0) {
                        break;
                    }
                    out.write(buffer, 0, read);
                    left -= read;
                }
            } catch (IOException e) {
                // the browser went away; nothing to clean up
            }
        };
        return builder.entity(output)
                .header("Content-Type", "video/mp4")
                .header("Content-Length", count)
                .header("Accept-Ranges", "bytes")
                .header("Content-Disposition",
                        "attachment".equalsIgnoreCase(disposition) || clip.shareable()
                                ? "attachment; filename=\"" + filename + "\"" : "inline")
                // Same clip, same bytes, for as long as the cache holds it.
                .header("Cache-Control", "private, max-age=86400")
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
        // CNMS answers with its own absolute address on the media port; the
        // browser wants it through this site (see Cmsv9Manager.forBrowser).
        String flvUrl = cmsv9Manager.forBrowser(resp.path("resultData").path("httpurl").asText(""));
        if (flvUrl == null || flvUrl.isEmpty()) {
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
