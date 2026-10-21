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
import org.traccar.helper.UnitsConverter;
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
    // A camera added in CNMS should show up here while the fitter is still at the
    // vehicle, so the device list is re-read every minute rather than every five.
    private static final long DEVICE_SYNC_INTERVAL_MINUTES = 1;
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
            Position last = currentPosition(device);
            boolean tracked = last != null && !"cnms".equals(last.getProtocol()) && last.getFixTime() != null;
            if (tracked && System.currentTimeMillis() - last.getFixTime().getTime() < TRACKER_FRESH_MS) {
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

                // The CNMS API reports speed in 0.1 km/h units; Traccar stores knots.
                // (It used to divide the raw value by 3.6, which both kept the 0.1
                // scale and converted to m/s, so speeds showed about 5x too high.)
                double speedKmh = data.path("speed").asDouble(0) / 10.0;
                position.setSpeed(UnitsConverter.knotsFromKph(speedKmh));
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

                // The fallback must not drag the vehicle backwards. Once a tracker has
                // gone quiet for longer than TRACKER_FRESH_MS the DVR takes over, but
                // only with a fix newer than the one the tracker already reported -
                // otherwise a camera sitting on an old fix replaces a later position.
                if (tracked && !position.getFixTime().after(last.getFixTime())) {
                    cSkipTracker++;
                    continue;
                }

                position.set(Position.KEY_IGNITION, acc);
                // How many satellites the unit can see, which is the difference
                // between "parked somewhere enclosed" and "the GPS aerial is not
                // working". A camera reporting for days on end with none of them
                // has a fault, and without this nobody could tell.
                int satellites = satelliteCount(data);
                if (satellites >= 0) {
                    position.set(Position.KEY_SATELLITES, satellites);
                }

                // Mileage comes in 0.1 km units as well; Traccar stores metres.
                //
                // Not on a vehicle that also has a tracker, though. The two
                // count from different starting points, so a camera position
                // landing between two tracker ones sends the odometer
                // backwards, and every report built on it reads a negative
                // trip. One vehicle gets one odometer: the tracker's where
                // there is a tracker, the camera's where there is not.
                if (!hasTracker(device)) {
                    position.set(Position.KEY_TOTAL_DISTANCE, data.path("summileage").asDouble(0) * 100.0);
                }
                position.set("cnmsOnline", carstatus > 0 && carstatus != 2);
                position.set("cnmsAddress", data.path("baiduAddress").asText(""));
                position.set("cnmsMileage", data.path("mileage").asDouble(0) * 100.0);

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

    /**
     * The position the vehicle is actually showing.
     *
     * This used to be read from the live cache, which only holds a position while the
     * device has a session - and a Teltonika unit connects, sends its records and
     * disconnects every few seconds, so most of the time the cache held nothing for
     * it. The tracker check therefore found no fix, the DVR fallback ran anyway, and
     * the camera's older fix was written over the tracker's: the cycle logged "0
     * tracker-preferred" while the tracker was reporting every five seconds, and the
     * vehicle's position flipped between the two every 15 seconds.
     *
     * The stored position is what the device is showing whether or not it happens to
     * be connected at this instant, which is the question being asked here.
     */
    private Position currentPosition(Device device) throws StorageException {
        if (device.getPositionId() > 0) {
            Position stored = storage.getObject(Position.class, new Request(
                    new Columns.All(), new Condition.Equals("id", device.getPositionId())));
            if (stored != null) {
                return stored;
            }
        }
        return cacheManager.getPosition(device.getId());
    }

    /**
     * Carries a rename in CNMS across to the vehicle here, but only while nobody has
     * renamed it locally: a camera is usually added under a placeholder name and
     * given its registration minutes later, and that should not need doing twice.
     */
    private void renameFromCnms(Device device, String nodeName) {
        if (device == null || nodeName.isBlank() || nodeName.equals(device.getName())) {
            return;
        }
        String knownAs = device.getString("cmsv9Name");
        if (knownAs == null || !knownAs.equals(device.getName())) {
            return;   // renamed here, or linked before we started tracking the CNMS name
        }
        try {
            String previous = device.getName();
            device.setName(nodeName);
            device.getAttributes().put("cmsv9Name", nodeName);
            storage.updateObject(device, new Request(
                    new Columns.Include("name", "attributes"),
                    new Condition.Equals("id", device.getId())));
            cacheManager.invalidateObject(true, Device.class, device.getId(), ObjectOperation.UPDATE);
            LOG.info("Renamed device {} from '{}' to '{}' (renamed in CNMS)", device.getId(), previous, nodeName);
        } catch (Exception e) {
            LOG.warn("Could not rename device {} to '{}': {}", device.getId(), nodeName, e.getMessage());
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
            Map<String, Device> linkedDevices = new HashMap<>();
            Map<String, Device> trackersByPlate = new HashMap<>();
            // Standalone auto-created placeholders (uniqueId "cnms-<terminal>") that we
            // previously created; kept so we can spot ones that should fold into a tracker.
            Map<String, Device> placeholders = new HashMap<>();
            for (Device device : storage.getObjects(Device.class, new Request(
                    new Columns.Include("id", "name", "uniqueId", "attributes")))) {
                String linked = device.getString("cmsv9DeviceId");
                if (linked != null && !linked.isBlank()) {
                    linkedTerminals.add(linked);
                    linkedDevices.put(linked, device);
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
                if (terminal.isBlank()) {
                    continue;
                }
                if (linkedTerminals.contains(terminal)) {
                    renameFromCnms(linkedDevices.get(terminal), node.path("nodeName").asText(""));
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
                    // What CNMS called it when we created it. While the local name still
                    // matches this, a rename in CNMS is carried across (see renameFromCnms);
                    // once someone renames the vehicle here, that name is left alone.
                    device.getAttributes().put("cmsv9Name", nodeName);

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

    // CNMS/CMSV9 gpstime is "yyMMddHHmmss" in UK local time, e.g. "260908060034"
    // = 2026-09-08 06:00:34 London. It is not day-first (decoding it as ddMMyy
    // stamped every fix in ~2008, so date-ranged reports found nothing) and not
    // server-local either - this machine's clock is set to UTC-6, which is what
    // put fixes in the future the first time that was tried.
    //
    // It was read as UTC until a live check settled it: with UTC 15:54 and London
    // 16:54, every connected camera was reporting 16:54. Reading those as UTC
    // stamped each one an hour ahead of real time for the whole of British Summer
    // Time, which skewed last-update, trips and every date-ranged report. In
    // winter the two agree, which is why it went unseen.
    //
    // Positions already stored during BST keep their one-hour error; only new
    // ones are right. The hour that repeats when the clocks go back resolves to
    // the first (BST) occurrence, which is the normal convention.
    private static final java.time.ZoneId CNMS_ZONE = java.time.ZoneId.of("Europe/London");

    /**
     * Satellites in view, or -1 when the record does not say.
     *
     * <p>The platform's own database calls this lGNSSStarCount; its API has been
     * seen to spell it several ways, so each likely name is tried and the first
     * one present wins. When none of them is there the field names are logged
     * once per run, which is the quickest way to learn the right one rather than
     * guessing again.
     */
    private int satelliteCount(com.fasterxml.jackson.databind.JsonNode data) {
        for (String name : new String[] {
                "lGNSSStarCount", "gnssstarcount", "gnssStarCount", "starcount", "starCount",
                "satellite", "satellites", "starnum", "star"}) {
            if (data.hasNonNull(name)) {
                return data.path(name).asInt(-1);
            }
        }
        if (!satelliteFieldReported) {
            satelliteFieldReported = true;
            StringBuilder names = new StringBuilder();
            data.fieldNames().forEachRemaining(name -> names.append(name).append(' '));
            LOG.info("CNMS gps record carries no satellite count; fields are: {}", names.toString().trim());
        }
        return -1;
    }

    private boolean satelliteFieldReported;

    /** Whether this vehicle has a tracker of its own as well as a camera. */
    private boolean hasTracker(Device device) {
        String imei = device.getString("trackerImei");
        String model = device.getString("trackerModel");
        return (imei != null && !imei.isBlank()) || (model != null && !model.isBlank());
    }

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
            Date parsed = Date.from(java.time.LocalDateTime.of(
                    Integer.parseInt(year), Integer.parseInt(month), Integer.parseInt(day),
                    Integer.parseInt(hour), Integer.parseInt(min), Integer.parseInt(sec))
                    .atZone(CNMS_ZONE).toInstant());
            // A DVR without a GPS fix sends a garbage clock (years in the future, or
            // long past). Such a time would file the position at the wrong date and
            // hide the vehicle's real last position, so treat it as unknown and let
            // the caller fall back to the server clock.
            long now = System.currentTimeMillis();
            if (parsed.getTime() > now + TimeUnit.DAYS.toMillis(1)
                    || parsed.getTime() < now - TimeUnit.DAYS.toMillis(365)) {
                return null;
            }
            return parsed;
        } catch (Exception e) {
            return null;
        }
    }
}
