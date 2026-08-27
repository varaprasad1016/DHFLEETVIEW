package com.dhfleetview.bridge;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Properties;
import java.util.UUID;

/**
 * Bridge local configuration. Stored next to the JAR as {@code bridge.properties}.
 * Secrets are stored via the OS credential store where available; for the MVP
 * the token is stored in the properties file with restricted permissions.
 * Never commit this file.
 */
public class BridgeConfig {

    private static final String FILE_NAME = "bridge.properties";

    private final File file;
    private final Properties props = new Properties();

    private BridgeConfig(File file) {
        this.file = file;
        if (file.exists()) {
            try (FileInputStream in = new FileInputStream(file)) {
                props.load(in);
            } catch (IOException ignored) {
            }
        }
    }

    public static BridgeConfig load() {
        File file = new File(FILE_NAME);
        if (!file.exists()) {
            file = new File("tacho-bridge/" + FILE_NAME);
        }
        if (!file.exists()) {
            file = new File(System.getProperty("user.home"), ".dhfleetview-bridge.properties");
        }
        return new BridgeConfig(file);
    }

    public String getServerUrl() {
        return props.getProperty("serverUrl", "https://dhfleetview.co.uk");
    }

    public void setServerUrl(String serverUrl) {
        props.setProperty("serverUrl", serverUrl);
    }

    public String getBridgeId() {
        return props.getProperty("bridgeId");
    }

    public void setBridgeId(String bridgeId) {
        props.setProperty("bridgeId", bridgeId);
    }

    public Long getBridgeNumericId() {
        String v = props.getProperty("bridgeNumericId");
        if (v == null) return null;
        try {
            return Long.parseLong(v);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public void setBridgeNumericId(Long id) {
        if (id == null) {
            props.remove("bridgeNumericId");
        } else {
            props.setProperty("bridgeNumericId", String.valueOf(id));
        }
    }

    public String getBridgeName() {
        return props.getProperty("bridgeName", "Tacho Bridge");
    }

    public void setBridgeName(String name) {
        props.setProperty("bridgeName", name);
    }

    public String getBridgeToken() {
        return props.getProperty("bridgeToken");
    }

    public void setBridgeToken(String token) {
        props.setProperty("bridgeToken", token);
    }

    public void save() throws IOException {
        File parent = file.getParentFile();
        if (parent != null) {
            parent.mkdirs();
        }
        try (FileOutputStream out = new FileOutputStream(file)) {
            props.store(out, "DH FleetView Tacho Bridge - do not commit");
        }
    }
}
