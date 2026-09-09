package org.traccar.schedule;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.media.Cmsv9Manager;
import org.traccar.model.Device;
import org.traccar.model.ObjectOperation;
import org.traccar.model.Permission;
import org.traccar.model.Position;
import org.traccar.model.User;
import org.traccar.session.ConnectionManager;
import org.traccar.session.cache.CacheManager;
import org.traccar.storage.Storage;
import org.traccar.storage.StorageException;
import org.traccar.storage.query.Columns;
import org.traccar.storage.query.Condition;
import org.traccar.storage.query.Request;

import jakarta.inject.Inject;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class TaskCnmsSync extends SingleScheduleTask {

    private static final Logger LOG = LoggerFactory.getLogger(TaskCnmsSync.class);

    private static final long GPS_SYNC_INTERVAL_SECONDS = 15;
    private static final long DEVICE_SYNC_INTERVAL_MINUTES = 5;
    // A real tracker takes priority over the DVR's GPS. While a device has a fix
    // from an actual tracker no older than this, the DVR GPS fallback is skipped.
    private static final long TRACKER_FRESH_MS = TimeUnit.MINUTES.toMillis(30);

    private final Storage storage;
    private final CacheManager cacheManager;
    private final ConnectionManager connectionManager;
    private final Cmsv9Manager cmsv9Manager;

    private long lastDeviceSync = 0;
    private long lastGpsReport = 0;

    @Inject
    public TaskCnmsSync(
            Storage storage,
            CacheManager cacheManager,
            ConnectionManager connectionManager,
            Cmsv9Manager cmsv9Manager) {
        this.storage = storage;
        this.cacheManager = cacheManager;
        this.connectionManager = connectionManager;
        this.cmsv9Manager = cmsv9Manager;
    }

    @Override
    public void schedule(ScheduledExecutorService executor) {
        executor.scheduleAtFixedRate(
                this, GPS_SYNC_INTERVAL_SECONDS, GPS_SYNC_INTERVAL_SECONDS, TimeUnit.SECONDS);
    }

    @Override
    public void run() {
        try {
            syncGpsPositions();
        } catch (Exception e) {
            LOG.warn("CNMS GPS sync error", e);
        }

        long now = System.currentTimeMillis();
        if (now - lastDeviceSync > TimeUnit.MINUTES.toMillis(DEVICE_SYNC_INTERVAL_MINUTES)) {
            lastDeviceSync = now;
            try {
                syncDevices();
            } catch (Exception e) {
                LOG.warn("CNMS device sync error", e);
            }
        }
    }

    private void syncGpsPositions() throws StorageException {
        if (!cmsv9Manager.isConfigured()) {
            return;
        }

        int cLinked = 0;
        int cErr = 0;
        int cEmpty = 0;
        int cZero = 0;
        int cSkipTracker = 0;
        int cWritten = 0;
        boolean report = System.currentTimeMillis() - lastGpsReport > TimeUnit.SECONDS.toMillis(60);

        for (Device device : storage.getObjects(Device.class, new Request(new Columns.All()))) {
            String terminal = device.getString("cmsv9DeviceId");
            if (terminal == null || terminal.isBlank()) {
                continue;
            }
            cLinked++;

            // Hierarchy: prefer a real tracker. If this device has a recent fix from an
            // actual tracker (any protocol other than our CNMS pull), skip the DVR GPS
            // fallback so tracker data drives trips and reports; the DVR GPS is only
            // written when no fresh tracker fix exists.
            Position last = cacheManager.getPosition(device.getId());
            if (last != null && !"cnms".equals(last.getProtocol()) && last.getFixTime() != null
                    && System.currentTimeMillis() - last.getFixTime().getTime() < TRACKER_FRESH_MS) {
                cSkipTracker++;
                continue;
            }

            try {
                JsonNode response = cmsv9Manager.getGpsStatus(terminal);
                if (response.path("errCode").asInt(-1) != 0) {
                    cErr++;
                    if (report) {
                        LOG.info("CNMS GPS {}: errCode={} msg={}", terminal,
                                response.path("errCode").asInt(-1), response.path("resultMsg").asText(""));
                    }
                    continue;
                }
                JsonNode dataList = response.path("resultData");
                if (!dataList.isArray() || dataList.isEmpty()) {
                    cEmpty++;
                    continue;
                }

                JsonNode data = dataList.get(0);

                boolean acc = data.path("acc").asInt(0) == 1;
                int carstatus = data.path("carstatus").asInt(0);

                // Status is updated before the position guard below, so a terminal
                // that has no fix yet still gets a correct online/offline state.
                // carstatus 2 is what the portal itself renders as offline; ignition
                // is not a connectivity signal, so a parked vehicle stays online.
                if (connectionManager.getDeviceSession(device.getId()) == null) {
                    if (carstatus > 0 && carstatus != 2) {
                        connectionManager.updateDevice(device.getId(), Device.STATUS_ONLINE, new Date());
                    } else {
                        connectionManager.updateDevice(device.getId(), Device.STATUS_OFFLINE, null);
                    }
                }

                double lat = data.path("lat").asDouble(0);
                double lng = data.path("lng").asDouble(0);
                if (lat == 0 && lng == 0) {
                    lat = data.path("blat").asDouble(0);
                    lng = data.path("blng").asDouble(0);
                }

                // A terminal that has never reported comes back as an all-null record
                // with an epoch-zero gpstime. Storing it would write a 0,0 fix on every
                // cycle, so skip until the device sends real coordinates.
                if (lat == 0 && lng == 0) {
                    cZero++;
                    continue;
                }

                Position position = new Position("cnms");
                position.setDeviceId(device.getId());
                position.setValid(data.path("gpsflag").asInt(0) == 1);
                position.setLatitude(lat);
                position.setLongitude(lng);
                position.setAltitude(data.path("altitude").asDouble(0));

                double speedKmh = data.path("speed").asDouble(0);
                position.setSpeed(speedKmh / 3.6);
                position.setCourse(data.path("direction").asDouble(0));

                String gpstime = data.path("gpstime").asText("");
                Date deviceTime = parseCnmsTime(gpstime);
                if (deviceTime != null) {
                    position.setDeviceTime(deviceTime);
                    position.setFixTime(deviceTime);
                } else {
                    position.setDeviceTime(new Date());
                    position.setFixTime(new Date());
                }

                position.set(Position.KEY_IGNITION, acc);
                position.set(Position.KEY_TOTAL_DISTANCE, data.path("summileage").asDouble(0));
                position.set("cnmsOnline", carstatus > 0 && carstatus != 2);
                position.set("cnmsAddress", data.path("baiduAddress").asText(""));
                position.set("cnmsMileage", data.path("mileage").asDouble(0));

                position.setServerTime(new Date());

                position.setId(storage.addObject(position, new Request(new Columns.Exclude("id"))));

                Device updatedDevice = new Device();
                updatedDevice.setId(device.getId());
                updatedDevice.setPositionId(position.getId());
                storage.updateObject(updatedDevice, new Request(
                        new Columns.Include("positionId"),
                        new Condition.Equals("id", device.getId())));

                var key = new Object();
                try {
                    cacheManager.addDevice(device.getId(), key);
                    cacheManager.updatePosition(position);
                    connectionManager.updatePosition(true, position);
                } finally {
                    cacheManager.removeDevice(device.getId(), key);
                }
                cWritten++;

            } catch (Exception e) {
                LOG.warn("CNMS GPS update failed for {}: {}", terminal, e.getMessage(), e);
            }
        }

        if (report) {
            lastGpsReport = System.currentTimeMillis();
            LOG.info("CNMS GPS cycle: {} linked, {} written, {} zero-fix, {} empty, {} errCode, {} tracker-preferred",
                    cLinked, cWritten, cZero, cEmpty, cErr, cSkipTracker);
        }
    }

    private void syncDevices() throws StorageException {
        if (!cmsv9Manager.isConfigured()) {
            return;
        }

        try {
            JsonNode response = cmsv9Manager.deptTree();
            if (response.path("errCode").asInt(-1) != 0) {
                return;
            }
            JsonNode list = response.path("resultData");
            if (!list.isArray()) {
                return;
            }

            // Load every device once and index them:
            //  - terminals already linked to a DVR (via the cmsv9DeviceId attribute)
            //  - unlinked tracker devices, keyed by their normalised registration/plate,
            //    so a DVR can be auto-linked onto the matching tracker instead of
            //    spawning a separate "cnms-<terminal>" device.
            Set<String> linkedTerminals = new HashSet<>();
            Map<String, Device> trackersByPlate = new HashMap<>();
            // Standalone auto-created placeholders (uniqueId "cnms-<terminal>") that we
            // previously created; kept so we can spot ones that should fold into a tracker.
            Map<String, Device> placeholders = new HashMap<>();
            for (Device device : storage.getObjects(Device.class, new Request(
                    new Columns.Include("id", "name", "uniqueId", "attributes")))) {
                String linked = device.getString("cmsv9DeviceId");
                if (linked != null && !linked.isBlank()) {
                    linkedTerminals.add(linked);
                    String uid = device.getUniqueId();
                    if (uid != null && uid.startsWith("cnms-")) {
                        placeholders.put(linked, device);
                    }
                    continue;
                }
                // Candidate tracker for auto-linking. Key on the device name (the reg)
                // and, if present, an explicit plate/registration attribute.
                for (String plate : new String[] {
                        normalizePlate(device.getName()),
                        normalizePlate(device.getString("plate")),
                        normalizePlate(device.getString("registration"))}) {
                    if (!plate.isBlank()) {
                        trackersByPlate.putIfAbsent(plate, device);
                    }
                }
            }

            for (JsonNode node : list) {
                if (node.path("nodetype").asInt(0) != 2) {
                    continue;
                }
                String terminal = node.path("terminal").asText("");
                if (terminal.isBlank() || linkedTerminals.contains(terminal)) {
                    continue;
                }

                String nodeName = node.path("nodeName").asText(terminal);
                String plate = normalizePlate(nodeName);
                Device tracker = plate.isBlank() ? null : trackersByPlate.get(plate);

                if (tracker != null) {
                    // Auto-link: attach this DVR to the existing tracker so the vehicle
                    // is one device (tracker GPS preferred, DVR camera + GPS fallback).
                    tracker.getAttributes().put("cmsv9DeviceId", terminal);
                    storage.updateObject(tracker, new Request(
                            new Columns.Include("attributes"),
                            new Condition.Equals("id", tracker.getId())));
                    cacheManager.invalidateObject(true, Device.class, tracker.getId(), ObjectOperation.UPDATE);

                    // Prevent this tracker (and this terminal) from being reused.
                    linkedTerminals.add(terminal);
                    trackersByPlate.values().removeIf(d -> d.getId() == tracker.getId());

                    LOG.info("Auto-linked DVR {} to tracker '{}' (id {}) by registration {}",
                            terminal, tracker.getName(), tracker.getId(), nodeName);
                } else {
                    // No matching tracker: create a standalone CNMS (camera-only) device.
                    Device device = new Device();
                    device.setName(nodeName);
                    device.setUniqueId("cnms-" + terminal);
                    device.setCategory("CNMS");
                    device.getAttributes().put("cmsv9DeviceId", terminal);

                    long deviceId = storage.addObject(device, new Request(new Columns.Exclude("id")));
                    device.setId(deviceId);

                    storage.addPermission(new Permission(User.class, 2, Device.class, deviceId));
                    storage.addPermission(new Permission(User.class, 3, Device.class, deviceId));

                    cacheManager.invalidatePermission(true, User.class, 2, Device.class, deviceId, true);
                    connectionManager.invalidatePermission(true, User.class, 2, Device.class, deviceId, true);

                    linkedTerminals.add(terminal);
                    LOG.info("Auto-created CNMS device: {} ({})", device.getName(), terminal);
                }
            }

            // Consolidation: a standalone DVR placeholder that shares a registration
            // with a real tracker device is the same vehicle. Fold them into one device
            // by moving the camera link (cmsv9DeviceId) onto the tracker and deleting the
            // now-redundant placeholder. The tracker keeps its own GPS history; the
            // placeholder's pre-merge DVR-only positions are removed with it (cascade).
            int merged = 0;
            for (Map.Entry<String, Device> entry : placeholders.entrySet()) {
                String terminal = entry.getKey();
                Device placeholder = entry.getValue();
                String plate = normalizePlate(placeholder.getName());
                Device tracker = plate.isBlank() ? null : trackersByPlate.get(plate);
                if (tracker == null || tracker.getId() == placeholder.getId()) {
                    continue;
                }

                // 1. Attach the DVR to the tracker.
                tracker.getAttributes().put("cmsv9DeviceId", terminal);
                storage.updateObject(tracker, new Request(
                        new Columns.Include("attributes"),
                        new Condition.Equals("id", tracker.getId())));
                cacheManager.invalidateObject(true, Device.class, tracker.getId(), ObjectOperation.UPDATE);

                // 2. Delete the redundant placeholder (positions/permissions cascade).
                storage.removeObject(Device.class, new Request(
                        new Condition.Equals("id", placeholder.getId())));
                cacheManager.invalidateObject(true, Device.class, placeholder.getId(), ObjectOperation.DELETE);

                // Don't let this tracker be reused as a match this pass.
                trackersByPlate.values().removeIf(d -> d.getId() == tracker.getId());
                merged++;
                LOG.info("Merged DVR placeholder '{}' (id {}, terminal {}) into tracker '{}' (id {})",
                        placeholder.getName(), placeholder.getId(), terminal,
                        tracker.getName(), tracker.getId());
            }

            Set<Long> distinctTrackers = new HashSet<>();
            for (Device d : trackersByPlate.values()) {
                distinctTrackers.add(d.getId());
            }
            LOG.info("CNMS sync: {} unlinked tracker(s), {} DVR placeholder(s), {} merged this pass",
                    distinctTrackers.size(), placeholders.size(), merged);
        } catch (Exception e) {
            LOG.warn("CNMS deptTree sync failed", e);
        }
    }

    // Normalise a registration/plate for matching: upper-case, strip everything
    // that is not a letter or digit (spaces, dashes, etc.). "G10 JHL" -> "G10JHL".
    private static String normalizePlate(String value) {
        if (value == null) {
            return "";
        }
        return value.toUpperCase().replaceAll("[^A-Z0-9]", "");
    }

    // CNMS/CMSV9 gpstime is "yyMMddHHmmss" in UTC, e.g. "260908060034" =
    // 2026-09-08 06:00:34 UTC. (It is NOT day-first, and NOT server-local: decoding
    // it as ddMMyy stamped every fix in ~2008 so date-ranged reports found nothing;
    // decoding it as server-local put fixes in the future.)
    private Date parseCnmsTime(String gpstime) {
        if (gpstime == null || gpstime.length() < 12) {
            return null;
        }
        try {
            String year = "20" + gpstime.substring(0, 2);
            String month = gpstime.substring(2, 4);
            String day = gpstime.substring(4, 6);
            String hour = gpstime.substring(6, 8);
            String min = gpstime.substring(8, 10);
            String sec = gpstime.substring(10, 12);
            return Date.from(java.time.LocalDateTime.of(
                    Integer.parseInt(year), Integer.parseInt(month), Integer.parseInt(day),
                    Integer.parseInt(hour), Integer.parseInt(min), Integer.parseInt(sec))
                    .toInstant(java.time.ZoneOffset.UTC));
        } catch (Exception e) {
            return null;
        }
    }
}
