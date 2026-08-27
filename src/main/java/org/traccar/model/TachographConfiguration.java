/*
 * Copyright 2026 DH FleetView contributors
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
package org.traccar.model;

import java.util.Date;

import org.traccar.storage.QueryIgnore;
import org.traccar.storage.StorageName;

@StorageName("tc_tachograph_configurations")
public class TachographConfiguration extends BaseModel {

    private long deviceId;
    private boolean enabled;
    private boolean driverDownloadEnabled;
    private boolean vehicleDownloadEnabled;
    private int driverDownloadIntervalDays;
    private int vehicleDownloadIntervalDays;
    private Date lastDriverDownload;
    private Date lastVehicleDownload;
    private Date nextDriverDownload;
    private Date nextVehicleDownload;
    private Date createdAt;
    private Date updatedAt;

    private String deviceName;

    public long getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(long deviceId) {
        this.deviceId = deviceId;
    }

    public boolean getEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public boolean getDriverDownloadEnabled() {
        return driverDownloadEnabled;
    }

    public void setDriverDownloadEnabled(boolean driverDownloadEnabled) {
        this.driverDownloadEnabled = driverDownloadEnabled;
    }

    public boolean getVehicleDownloadEnabled() {
        return vehicleDownloadEnabled;
    }

    public void setVehicleDownloadEnabled(boolean vehicleDownloadEnabled) {
        this.vehicleDownloadEnabled = vehicleDownloadEnabled;
    }

    public int getDriverDownloadIntervalDays() {
        return driverDownloadIntervalDays;
    }

    public void setDriverDownloadIntervalDays(int driverDownloadIntervalDays) {
        this.driverDownloadIntervalDays = driverDownloadIntervalDays;
    }

    public int getVehicleDownloadIntervalDays() {
        return vehicleDownloadIntervalDays;
    }

    public void setVehicleDownloadIntervalDays(int vehicleDownloadIntervalDays) {
        this.vehicleDownloadIntervalDays = vehicleDownloadIntervalDays;
    }

    public Date getLastDriverDownload() {
        return lastDriverDownload;
    }

    public void setLastDriverDownload(Date lastDriverDownload) {
        this.lastDriverDownload = lastDriverDownload;
    }

    public Date getLastVehicleDownload() {
        return lastVehicleDownload;
    }

    public void setLastVehicleDownload(Date lastVehicleDownload) {
        this.lastVehicleDownload = lastVehicleDownload;
    }

    public Date getNextDriverDownload() {
        return nextDriverDownload;
    }

    public void setNextDriverDownload(Date nextDriverDownload) {
        this.nextDriverDownload = nextDriverDownload;
    }

    public Date getNextVehicleDownload() {
        return nextVehicleDownload;
    }

    public void setNextVehicleDownload(Date nextVehicleDownload) {
        this.nextVehicleDownload = nextVehicleDownload;
    }

    public Date getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Date createdAt) {
        this.createdAt = createdAt;
    }

    public Date getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Date updatedAt) {
        this.updatedAt = updatedAt;
    }

    @QueryIgnore
    public String getDeviceName() {
        return deviceName;
    }

    public void setDeviceName(String deviceName) {
        this.deviceName = deviceName;
    }
}
