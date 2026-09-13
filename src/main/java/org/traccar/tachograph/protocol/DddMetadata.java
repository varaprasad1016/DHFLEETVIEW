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
package org.traccar.tachograph.protocol;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;

/**
 * Descriptive fields read out of an assembled DDD file: enough to name the file the way the
 * regulation expects, to show an operator what a download actually contains, and to let an
 * analysis bureau match the file to a vehicle without opening it.
 *
 * <p>Fields that could not be read are left null rather than guessed. Generation 2 vehicle units
 * use variable-length certificates in the overview block, so only the fields that can be located
 * unambiguously are populated for those files.
 */
public class DddMetadata {

    private int generation = 1;
    private String vehicleIdentificationNumber;
    private String vehicleRegistrationNumber;
    private Integer vehicleRegistrationNation;
    private String vehicleUnitSerialNumber;
    private String vehicleUnitManufacturer;
    private String companyName;
    private String cardNumber;
    private String cardHolderName;
    private Date currentDateTime;
    private Date downloadablePeriodFrom;
    private Date downloadablePeriodTo;
    private final List<String> blocks = new ArrayList<>();
    private final List<String> warnings = new ArrayList<>();

    public int getGeneration() {
        return generation;
    }

    public void setGeneration(int generation) {
        this.generation = generation;
    }

    public String getVehicleIdentificationNumber() {
        return vehicleIdentificationNumber;
    }

    public void setVehicleIdentificationNumber(String vehicleIdentificationNumber) {
        this.vehicleIdentificationNumber = vehicleIdentificationNumber;
    }

    public String getVehicleRegistrationNumber() {
        return vehicleRegistrationNumber;
    }

    public void setVehicleRegistrationNumber(String vehicleRegistrationNumber) {
        this.vehicleRegistrationNumber = vehicleRegistrationNumber;
    }

    public Integer getVehicleRegistrationNation() {
        return vehicleRegistrationNation;
    }

    public void setVehicleRegistrationNation(Integer vehicleRegistrationNation) {
        this.vehicleRegistrationNation = vehicleRegistrationNation;
    }

    public String getVehicleUnitSerialNumber() {
        return vehicleUnitSerialNumber;
    }

    public void setVehicleUnitSerialNumber(String vehicleUnitSerialNumber) {
        this.vehicleUnitSerialNumber = vehicleUnitSerialNumber;
    }

    public String getVehicleUnitManufacturer() {
        return vehicleUnitManufacturer;
    }

    public void setVehicleUnitManufacturer(String vehicleUnitManufacturer) {
        this.vehicleUnitManufacturer = vehicleUnitManufacturer;
    }

    public String getCompanyName() {
        return companyName;
    }

    public void setCompanyName(String companyName) {
        this.companyName = companyName;
    }

    public String getCardNumber() {
        return cardNumber;
    }

    public void setCardNumber(String cardNumber) {
        this.cardNumber = cardNumber;
    }

    public String getCardHolderName() {
        return cardHolderName;
    }

    public void setCardHolderName(String cardHolderName) {
        this.cardHolderName = cardHolderName;
    }

    public Date getCurrentDateTime() {
        return currentDateTime;
    }

    public void setCurrentDateTime(Date currentDateTime) {
        this.currentDateTime = currentDateTime;
    }

    public Date getDownloadablePeriodFrom() {
        return downloadablePeriodFrom;
    }

    public void setDownloadablePeriodFrom(Date downloadablePeriodFrom) {
        this.downloadablePeriodFrom = downloadablePeriodFrom;
    }

    public Date getDownloadablePeriodTo() {
        return downloadablePeriodTo;
    }

    public void setDownloadablePeriodTo(Date downloadablePeriodTo) {
        this.downloadablePeriodTo = downloadablePeriodTo;
    }

    /** Labels of the TREP blocks present in the file, in file order. */
    public List<String> getBlocks() {
        return blocks;
    }

    /** Non-fatal observations, for example a mandatory block that the vehicle unit omitted. */
    public List<String> getWarnings() {
        return warnings;
    }

    public void addWarning(String warning) {
        warnings.add(warning);
    }
}
