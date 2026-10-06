/*
 * Copyright 2015 - 2025 Anton Tananaev (anton@traccar.org)
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

import jakarta.servlet.http.HttpServletRequest;
import jakarta.ws.rs.core.Context;
import org.traccar.api.BaseResource;
import org.traccar.model.ObjectOperation;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.database.OpenIdProvider;
import org.traccar.geocoder.Geocoder;
import org.traccar.helper.Log;
import org.traccar.helper.LogAction;
import org.traccar.helper.model.UserUtil;
import org.traccar.mail.MailManager;
import org.traccar.model.Server;
import org.traccar.model.User;
import org.traccar.session.cache.CacheManager;
import org.traccar.sms.SmsManager;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;

import jakarta.annotation.Nullable;
import jakarta.annotation.security.PermitAll;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Collection;
import java.util.List;
import java.util.TimeZone;

@Path("server")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
public class ServerResource extends BaseResource {

    @Inject
    private Config config;

    @Inject
    private CacheManager cacheManager;

    @Inject
    private MailManager mailManager;

    @Inject
    @Nullable
    private SmsManager smsManager;

    @Inject
    @Nullable
    private OpenIdProvider openIdProvider;

    @Inject
    @Nullable
    private Geocoder geocoder;

    @Inject
    private LogAction actionLogger;

    @Context
    private HttpServletRequest request;

    @PermitAll
    @GET
    public Server get() throws StorageException {
        Server server = storage.getObject(Server.class, new Request(new Columns.All()));
        server.setEmailEnabled(mailManager.getEmailEnabled());
        server.setTextEnabled(smsManager != null);
        server.setGeocoderEnabled(geocoder != null);
        server.setOpenIdEnabled(openIdProvider != null);
        server.setOpenIdForce(openIdProvider != null && openIdProvider.getForce());
        User user = permissionsService.getUser(getUserId());
        if (user != null) {
            if (user.getAdministrator()) {
                server.setStorageSpace(Log.getStorageSpace());
            }
        } else {
            server.setNewServer(UserUtil.isEmpty(storage));
        }
        return server;
    }

    @PUT
    public Response update(Server server) throws Exception {
        permissionsService.checkAdmin(getUserId());
        storage.updateObject(server, new Request(
                new Columns.Exclude("id"),
                new Condition.Equals("id", server.getId())));
        cacheManager.invalidateObject(true, Server.class, server.getId(), ObjectOperation.UPDATE);
        actionLogger.edit(request, getUserId(), server);
        return Response.ok(server).build();
    }

    @Path("geocode")
    @GET
    public String geocode(@QueryParam("latitude") double latitude, @QueryParam("longitude") double longitude) {
        if (geocoder != null) {
            return geocoder.getAddress(latitude, longitude, null);
        } else {
            throw new RuntimeException("Reverse geocoding is not enabled");
        }
    }

    @Path("timezones")
    @GET
    public Collection<String> timezones() {
        return List.of(TimeZone.getAvailableIDs());
    }

    @Path("file/{path}")
    @POST
    @Consumes("*/*")
    public Response uploadFile(@PathParam("path") String path, File inputFile) throws IOException, StorageException {
        permissionsService.checkAdmin(getUserId());
        String root = config.getString(Keys.WEB_OVERRIDE, config.getString(Keys.WEB_PATH));

        var rootPath = Paths.get(root).normalize();
        var outputPath = rootPath.resolve(path).normalize();
        if (!outputPath.startsWith(rootPath)) {
            return Response.status(Response.Status.BAD_REQUEST).build();
        }

        var directoryPath = outputPath.getParent();
        if (directoryPath != null) {
            Files.createDirectories(directoryPath);
        }

        try (var input = new FileInputStream(inputFile); var output = new FileOutputStream(outputPath.toFile())) {
            input.transferTo(output);
        }
        return Response.ok().build();
    }

    @Path("gc")
    @GET
    public Response gc() throws StorageException {
        permissionsService.checkAdmin(getUserId());
        System.gc();
        return Response.ok().build();
    }

    @Path("cache")
    @GET
    public String cache() throws StorageException {
        permissionsService.checkAdmin(getUserId());
        return cacheManager.toString();
    }

    /**
     * Refused, deliberately, for everybody including administrators.
     *
     * <p>This used to call {@code System.exit(130)}. On this deployment nothing
     * starts the process again afterwards - the Windows service has no recovery
     * actions configured - so it was not a reboot at all. It stopped tracking,
     * live video and the API for every customer until somebody logged into the
     * server and started the service by hand, and the button that called it sat
     * one click away from the version numbers people open Preferences to read.
     *
     * <p>Kept as a route rather than deleted so that an old cached page or a
     * bookmarked call gets a clear answer instead of a 404 that reads like a
     * bug. Restarting the service is an operator action, taken on the server.
     */
    @Path("reboot")
    @POST
    public void reboot() throws StorageException {
        permissionsService.checkAdmin(getUserId());
        throw new WebApplicationException(
                Response.status(Response.Status.FORBIDDEN)
                        .entity("Restarting the server from the web app is disabled. "
                                + "Nothing would bring the service back up, so this would take "
                                + "the platform offline for every user. Restart it on the server.")
                        .type(MediaType.TEXT_PLAIN)
                        .build());
    }

}
