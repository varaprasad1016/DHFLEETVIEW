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
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;

import org.traccar.api.BaseResource;
import org.traccar.model.Device;
import org.traccar.model.Position;
import org.traccar.model.User;
import org.traccar.roads.RoadDisruptionManager;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Closures, roadworks and lane restrictions on the strategic road network.
 *
 * `active` by default, because a map of everything National Highways has ever
 * planned is noise - 409 of the 500 records in a typical feed start weeks from
 * now. Pass `includePlanned=true` for the lot.
 *
 * `near` and `radius` answer the question that matters when a lorry is sitting
 * still: what is going on in front of it.
 */
@Path("disruptions")
@Produces(MediaType.APPLICATION_JSON)
public class DisruptionResource extends BaseResource {

    private static final double EARTH_RADIUS_KM = 6371.0;
    private static final int DEFAULT_RADIUS_KM = 25;

    @Inject
    private RoadDisruptionManager disruptionManager;

    @GET
    public Map<String, Object> get(
            @QueryParam("includePlanned") boolean includePlanned,
            @QueryParam("near") String near,
            @QueryParam("radius") Integer radiusKm) {

        List<RoadDisruptionManager.Disruption> all = disruptionManager.getDisruptions();

        var stream = all.stream();
        if (!includePlanned) {
            stream = stream.filter(RoadDisruptionManager.Disruption::isActive);
        }

        double[] origin = parsePoint(near);
        if (origin != null) {
            double limit = radiusKm != null ? radiusKm : DEFAULT_RADIUS_KM;
            stream = stream
                    .filter(d -> distanceKm(origin[0], origin[1], d.getLatitude(), d.getLongitude()) <= limit)
                    .sorted(Comparator.comparingDouble(
                            d -> distanceKm(origin[0], origin[1], d.getLatitude(), d.getLongitude())));
        }

        List<RoadDisruptionManager.Disruption> items = stream.toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("configured", disruptionManager.isConfigured());
        result.put("updated", disruptionManager.getFetchedAt().toString());
        result.put("total", all.size());
        result.put("count", items.size());
        if (disruptionManager.getLastError() != null) {
            result.put("error", disruptionManager.getLastError());
        }
        result.put("items", items);
        return result;
    }

    private static final double AHEAD_RADIUS_KM = 15;
    private static final double AHEAD_ANGLE_DEGREES = 55;
    private static final double MOVING_KNOTS = 3;
    private static final Pattern ROAD = Pattern.compile("\\b([AM]\\d{1,4}(?:\\(M\\))?)\\b");

    /**
     * What each moving vehicle is driving towards.
     *
     * Distance alone is useless on a road network: a closure two miles away on
     * the other carriageway, or behind, is not the driver's problem. A
     * disruption counts as ahead when it is within the radius *and* lies within
     * a cone around the vehicle's current course, which is what "approaching"
     * actually means.
     *
     * Where the vehicle's address names a road, a match against the
     * disruption's road is reported as well - that is the difference between
     * "something nearby" and "on your road", and the office can treat the two
     * differently.
     */
    @GET
    @Path("ahead")
    public Map<String, Object> ahead(
            @QueryParam("radius") Double radiusKm,
            @QueryParam("angle") Double angleDegrees) throws StorageException {

        double radius = radiusKm != null ? radiusKm : AHEAD_RADIUS_KM;
        double cone = angleDegrees != null ? angleDegrees : AHEAD_ANGLE_DEGREES;

        List<RoadDisruptionManager.Disruption> live = disruptionManager.getDisruptions().stream()
                .filter(RoadDisruptionManager.Disruption::isActive)
                .toList();

        var devices = storage.getObjects(Device.class, new Request(
                new Columns.All(), new Condition.Permission(User.class, getUserId(), Device.class)));
        Map<Long, Device> byId = new HashMap<>();
        devices.forEach(device -> byId.put(device.getId(), device));

        var positions = storage.getObjects(Position.class, new Request(
                new Columns.All(), new Condition.LatestPositions()));

        List<Map<String, Object>> warnings = new ArrayList<>();
        for (Position position : positions) {
            Device device = byId.get(position.getDeviceId());
            if (device == null || position.getSpeed() < MOVING_KNOTS) {
                continue;       // parked vehicles are not approaching anything
            }
            String vehicleRoad = roadIn(position.getAddress());
            RoadDisruptionManager.Disruption best = null;
            double bestDistance = Double.MAX_VALUE;
            boolean bestSameRoad = false;
            for (RoadDisruptionManager.Disruption d : live) {
                double distance = distanceKm(
                        position.getLatitude(), position.getLongitude(), d.getLatitude(), d.getLongitude());
                if (distance > radius) {
                    continue;
                }
                double bearing = bearingDegrees(
                        position.getLatitude(), position.getLongitude(), d.getLatitude(), d.getLongitude());
                if (angleBetween(position.getCourse(), bearing) > cone) {
                    continue;   // behind, or across the junction
                }
                boolean sameRoad = vehicleRoad != null && vehicleRoad.equals(d.getRoad());
                // A match on the road beats a closer one that merely happens to
                // lie in the same direction.
                if (best == null || (sameRoad && !bestSameRoad)
                        || (sameRoad == bestSameRoad && distance < bestDistance)) {
                    best = d;
                    bestDistance = distance;
                    bestSameRoad = sameRoad;
                }
            }
            if (best != null) {
                Map<String, Object> warning = new LinkedHashMap<>();
                warning.put("deviceId", device.getId());
                warning.put("name", device.getName());
                warning.put("distanceKm", Math.round(bestDistance * 10) / 10.0);
                warning.put("onSameRoad", bestSameRoad);
                warning.put("vehicleRoad", vehicleRoad);
                warning.put("disruption", best);
                warnings.add(warning);
            }
        }
        warnings.sort(Comparator.comparingDouble(w -> (double) w.get("distanceKm")));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("configured", disruptionManager.isConfigured());
        result.put("active", live.size());
        result.put("count", warnings.size());
        result.put("items", warnings);
        return result;
    }

    /** The road a vehicle appears to be on, from whatever its address says. */
    private String roadIn(String address) {
        if (address == null) {
            return null;
        }
        Matcher matcher = ROAD.matcher(address.toUpperCase(Locale.UK));
        return matcher.find() ? matcher.group(1) : null;
    }

    /** Initial bearing from one point to another, degrees from north. */
    private double bearingDegrees(double lat1, double lon1, double lat2, double lon2) {
        double phi1 = Math.toRadians(lat1);
        double phi2 = Math.toRadians(lat2);
        double dLon = Math.toRadians(lon2 - lon1);
        double y = Math.sin(dLon) * Math.cos(phi2);
        double x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
        return (Math.toDegrees(Math.atan2(y, x)) + 360) % 360;
    }

    /** The smaller angle between two headings, so 350 and 10 are 20 apart. */
    private double angleBetween(double a, double b) {
        double diff = Math.abs(a - b) % 360;
        return diff > 180 ? 360 - diff : diff;
    }

    private double[] parsePoint(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String[] parts = value.split(",");
        if (parts.length != 2) {
            return null;
        }
        try {
            return new double[] {Double.parseDouble(parts[0].trim()), Double.parseDouble(parts[1].trim())};
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private double distanceKm(double lat1, double lon1, double lat2, double lon2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLon = Math.toRadians(lon2 - lon1);
        double a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
                * Math.sin(dLon / 2) * Math.sin(dLon / 2);
        return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }
}
