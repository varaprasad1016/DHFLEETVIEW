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

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Date;

import org.traccar.storage.QueryIgnore;
import org.traccar.storage.StorageName;

/**
 * Where completed DDD files are delivered: an analysis bureau such as Convey Reporting, or any
 * other destination the operator has an account with.
 *
 * <p>A target belongs to a group, so a multi-company installation delivers each company's files
 * to that company's own bureau account. Group zero means every device on the server.
 */
@StorageName("tc_tachograph_forward_targets")
public class TachographForwardTarget extends BaseModel {

    /** Convey Reporting, the analysis bureau this installation was built around. */
    public static final String PROVIDER_CONVEY = "CONVEY";
    /** Any other bureau or archive reachable by the same transports. */
    public static final String PROVIDER_GENERIC = "GENERIC";

    /** Deliver by SFTP, which is how most bureaux accept bulk DDD files. */
    public static final String TRANSPORT_SFTP = "SFTP";
    /** Deliver by HTTPS upload to an API endpoint. */
    public static final String TRANSPORT_HTTPS = "HTTPS";

    public static final String STATUS_OK = "OK";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_UNTESTED = "UNTESTED";

    private long groupId;
    private String name;
    private String provider;
    private String transport;
    private boolean enabled;
    private String host;
    private int port;
    private String username;
    private String secret;
    private String remotePath;
    private String url;
    private String hostKey;
    private String fileNamePattern;
    private boolean forwardDriver;
    private boolean forwardVehicle;
    private String lastStatus;
    private String lastMessage;
    private Date lastAttemptAt;
    private Date lastSuccessAt;
    private Date createdAt;
    private Date updatedAt;

    private String groupName;
    private String secretInput;

    public long getGroupId() {
        return groupId;
    }

    public void setGroupId(long groupId) {
        this.groupId = groupId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    /** {@link #PROVIDER_CONVEY} or {@link #PROVIDER_GENERIC}. */
    public String getProvider() {
        return provider;
    }

    public void setProvider(String provider) {
        this.provider = provider;
    }

    /** {@link #TRANSPORT_SFTP} or {@link #TRANSPORT_HTTPS}. */
    public String getTransport() {
        return transport;
    }

    public void setTransport(String transport) {
        this.transport = transport;
    }

    public boolean getEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getHost() {
        return host;
    }

    public void setHost(String host) {
        this.host = host;
    }

    public int getPort() {
        return port;
    }

    public void setPort(int port) {
        this.port = port;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    /**
     * The encrypted password or API key. Never serialised: a credential that has been stored
     * must not be readable back through the API, only replaced.
     */
    @JsonIgnore
    public String getSecret() {
        return secret;
    }

    public void setSecret(String secret) {
        this.secret = secret;
    }

    /** Directory on the remote server that files are written into. */
    public String getRemotePath() {
        return remotePath;
    }

    public void setRemotePath(String remotePath) {
        this.remotePath = remotePath;
    }

    /** Endpoint for HTTPS delivery. */
    public String getUrl() {
        return url;
    }

    public void setUrl(String url) {
        this.url = url;
    }

    /**
     * The expected SSH host key for SFTP delivery, base64 encoded. Pinning it is what stops a
     * DDD file, which carries a driver's whole working record, going to an impostor.
     */
    public String getHostKey() {
        return hostKey;
    }

    public void setHostKey(String hostKey) {
        this.hostKey = hostKey;
    }

    /**
     * How remote file names are built. Supports {@code {name}}, {@code {device}},
     * {@code {registration}}, {@code {type}} and {@code {timestamp}}. Empty keeps the local name.
     */
    public String getFileNamePattern() {
        return fileNamePattern;
    }

    public void setFileNamePattern(String fileNamePattern) {
        this.fileNamePattern = fileNamePattern;
    }

    public boolean getForwardDriver() {
        return forwardDriver;
    }

    public void setForwardDriver(boolean forwardDriver) {
        this.forwardDriver = forwardDriver;
    }

    public boolean getForwardVehicle() {
        return forwardVehicle;
    }

    public void setForwardVehicle(boolean forwardVehicle) {
        this.forwardVehicle = forwardVehicle;
    }

    public String getLastStatus() {
        return lastStatus;
    }

    public void setLastStatus(String lastStatus) {
        this.lastStatus = lastStatus;
    }

    public String getLastMessage() {
        return lastMessage;
    }

    public void setLastMessage(String lastMessage) {
        this.lastMessage = lastMessage;
    }

    public Date getLastAttemptAt() {
        return lastAttemptAt;
    }

    public void setLastAttemptAt(Date lastAttemptAt) {
        this.lastAttemptAt = lastAttemptAt;
    }

    public Date getLastSuccessAt() {
        return lastSuccessAt;
    }

    public void setLastSuccessAt(Date lastSuccessAt) {
        this.lastSuccessAt = lastSuccessAt;
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
    public String getGroupName() {
        return groupName;
    }

    public void setGroupName(String groupName) {
        this.groupName = groupName;
    }

    /**
     * A new plaintext credential supplied by an operator. Accepted on the way in, encrypted into
     * {@link #getSecret()}, and never returned.
     *
     * <p>Write-only rather than ignored: {@code @JsonIgnore} would also stop the value binding
     * from the request body, which would silently discard every credential an operator entered.
     */
    @QueryIgnore
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    public String getSecretInput() {
        return secretInput;
    }

    public void setSecretInput(String secretInput) {
        this.secretInput = secretInput;
    }

    /** Whether a credential is stored, without revealing it. */
    @QueryIgnore
    public boolean getHasSecret() {
        return secret != null && !secret.isBlank();
    }

    /** Whether this target should receive a file of the given type. */
    public boolean accepts(String fileType) {
        if (TachographFile.TYPE_DRIVER.equals(fileType)) {
            return forwardDriver;
        }
        return forwardVehicle;
    }
}
