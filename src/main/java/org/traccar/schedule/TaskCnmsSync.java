package org.traccar.schedule;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.media.Cmsv9Manager;
import org.traccar.model.Device;
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
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class TaskCnmsSync extends SingleScheduleTask {

    private static final Logger LOG = LoggerFactory.getLogger(TaskCnmsSync.class);

    private static final long GPS_SYNC_INTERVAL_SECONDS = 15;
    private static final long DEVICE_SYNC_INTERVAL_MINUTES = 5;

    private final Storage storage;
    private final CacheManager cacheManager;
    private final ConnectionManager connectionManager;
    private final Cmsv9Manager cmsv9Manager;

    private long lastDeviceSync = 0;

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

        for (Device device : storage.getObjects(Device.class, new Request(new Columns.All()))) {
            String terminal = device.getString("cmsv9DeviceId");
            if (terminal == null || terminal.isBlank()) {
                continue;
            }

            try {
                JsonNode response = cmsv9Manager.getGpsStatus(terminal);
                if (response.path("errCode").asInt(-1) != 0) {
                    continue;
                }
                JsonNode dataList = response.path("resultData");
                if (!dataList.isArray() || dataList.isEmpty()) {
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

            } catch (Exception e) {
                LOG.debug("CNMS GPS update failed for {}: {}", terminal, e.getMessage());
            }
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

            for (JsonNode node : list) {
                if (node.path("nodetype").asInt(0) != 2) {
                    continue;
                }
                String terminal = node.path("terminal").asText("");
                if (terminal.isBlank()) {
                    continue;
                }

                boolean exists = false;
                Request deviceRequest = new Request(new Columns.Include("id", "attributes"));
                for (Device device : storage.getObjects(Device.class, deviceRequest)) {
                    if (terminal.equals(device.getString("cmsv9DeviceId"))) {
                        exists = true;
                        break;
                    }
                }

                if (!exists) {
                    Device device = new Device();
                    device.setName(node.path("nodeName").asText(terminal));
                    device.setUniqueId("cnms-" + terminal);
                    device.setCategory("CNMS");
                    device.getAttributes().put("cmsv9DeviceId", terminal);

                    long deviceId = storage.addObject(device, new Request(new Columns.Exclude("id")));
                    device.setId(deviceId);

                    storage.addPermission(new Permission(User.class, 2, Device.class, deviceId));
                    storage.addPermission(new Permission(User.class, 3, Device.class, deviceId));

                    cacheManager.invalidatePermission(true, User.class, 2, Device.class, deviceId, true);
                    connectionManager.invalidatePermission(true, User.class, 2, Device.class, deviceId, true);

                    LOG.info("Auto-created CNMS device: {} ({})", device.getName(), terminal);
                }
            }
        } catch (Exception e) {
            LOG.warn("CNMS deptTree sync failed", e);
        }
    }

    private Date parseCnmsTime(String gpstime) {
        if (gpstime == null || gpstime.length() < 12) {
            return null;
        }
        try {
            String year = "20" + gpstime.substring(4, 6);
            String month = gpstime.substring(2, 4);
            String day = gpstime.substring(0, 2);
            String hour = gpstime.substring(6, 8);
            String min = gpstime.substring(8, 10);
            String sec = gpstime.substring(10, 12);
            return Date.from(java.time.LocalDateTime.of(
                    Integer.parseInt(year), Integer.parseInt(month), Integer.parseInt(day),
                    Integer.parseInt(hour), Integer.parseInt(min), Integer.parseInt(sec))
                    .atZone(java.time.ZoneId.systemDefault()).toInstant());
        } catch (Exception e) {
            return null;
        }
    }
}
