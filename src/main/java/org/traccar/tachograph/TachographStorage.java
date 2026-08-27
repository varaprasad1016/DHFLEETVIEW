/*
 * Copyright 2026 DH FleetView contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package org.traccar.tachograph;

import org.traccar.config.Config;
import org.traccar.config.Keys;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/**
 * Local filesystem storage for tachograph DDD files.
 * Files are stored under {storageRoot}/{groupId}/{deviceId}/{year}/{month}/.
 * All paths are validated against traversal.
 */
@Singleton
public class TachographStorage {

    private static final DateTimeFormatter YEAR = DateTimeFormatter.ofPattern("yyyy");
    private static final DateTimeFormatter MONTH = DateTimeFormatter.ofPattern("MM");

    private final Config config;

    @Inject
    public TachographStorage(Config config) {
        this.config = config;
    }

    public String getRoot() {
        String root = config.getString(Keys.TACHO_STORAGE_PATH);
        if (root == null || root.isBlank()) {
            root = "data/tachograph";
        }
        return root;
    }

    public Path resolveFinalPath(long groupId, long deviceId, String fileName) throws IOException {
        validateFileName(fileName);
        Instant now = Instant.now();
        String year = YEAR.format(now.atZone(ZoneId.systemDefault()));
        String month = MONTH.format(now.atZone(ZoneId.systemDefault()));

        String safeGroup = sanitize(String.valueOf(groupId));
        String safeDevice = sanitize(String.valueOf(deviceId));

        Path dir = Path.of(getRoot(), safeGroup, safeDevice, year, month);
        Files.createDirectories(dir);
        Path file = dir.resolve(fileName).normalize();
        if (!file.startsWith(Path.of(getRoot()).toAbsolutePath().normalize())
                && !file.toAbsolutePath().startsWith(
                        Path.of(getRoot()).toAbsolutePath().normalize())) {
            // also allow relative root
            if (!file.normalize().startsWith(dir.normalize())) {
                throw new IOException("Path traversal detected: " + fileName);
            }
        }
        return file;
    }

    public Path createTempFile() throws IOException {
        Path tmpDir = Path.of(getRoot(), ".tmp");
        Files.createDirectories(tmpDir);
        return Files.createTempFile(tmpDir, "tacho-", ".tmp");
    }

    public void moveTempToFinal(Path tempFile, Path finalPath) throws IOException {
        Files.createDirectories(finalPath.getParent());
        Files.move(tempFile, finalPath, StandardCopyOption.REPLACE_EXISTING);
    }

    public String calculateSha256(Path file) throws IOException {
        try (InputStream in = Files.newInputStream(file)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) != -1) {
                digest.update(buffer, 0, read);
            }
            byte[] hash = digest.digest();
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IOException("SHA-256 calculation failed", e);
        }
    }

    public String calculateSha256(byte[] data) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(data);
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IOException("SHA-256 calculation failed", e);
        }
    }

    public void writeBytes(Path tempFile, byte[] data) throws IOException {
        try (OutputStream out = new FileOutputStream(tempFile.toFile())) {
            out.write(data);
        }
    }

    public long fileSize(Path file) throws IOException {
        return Files.size(file);
    }

    private void validateFileName(String fileName) throws IOException {
        if (fileName == null || fileName.isBlank()) {
            throw new IOException("File name is empty");
        }
        if (fileName.contains("..") || fileName.contains("/") || fileName.contains("\\")) {
            // allow only simple names; subdirectories are managed by storage, not user input
            // DDD files typically contain '_' and '.' only
            if (fileName.contains("..")) {
                throw new IOException("Path traversal in file name: " + fileName);
            }
            // any slash is rejected
            if (fileName.contains("/") || fileName.contains("\\")) {
                throw new IOException("File name must not contain path separators: " + fileName);
            }
        }
        // additional safety: no absolute path
        File f = new File(fileName);
        if (f.isAbsolute()) {
            throw new IOException("Absolute file name not allowed: " + fileName);
        }
    }

    private String sanitize(String input) {
        return input.replaceAll("[^a-zA-Z0-9._-]", "_");
    }
}
