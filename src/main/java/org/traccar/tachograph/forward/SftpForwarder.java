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
package org.traccar.tachograph.forward;

import net.schmizz.sshj.SSHClient;
import net.schmizz.sshj.sftp.SFTPClient;
import net.schmizz.sshj.common.Buffer;
import net.schmizz.sshj.transport.TransportException;
import net.schmizz.sshj.transport.verification.HostKeyVerifier;
import net.schmizz.sshj.transport.verification.PromiscuousVerifier;
import net.schmizz.sshj.userauth.UserAuthException;
import net.schmizz.sshj.userauth.keyprovider.KeyProvider;
import net.schmizz.sshj.xfer.FileSystemFile;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.model.TachographForwardTarget;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.io.IOException;
import java.nio.file.Path;
import java.security.PublicKey;
import java.util.Base64;
import java.util.List;

/**
 * Delivers DDD files over SFTP, which is how most tachograph analysis bureaux, Convey Reporting
 * included, accept bulk uploads.
 *
 * <p>Files are written to a temporary name and renamed into place once the bytes are all there.
 * Bureaux poll their inbound directory on a timer, and a poll that catches a half-written file
 * either imports a truncated record or rejects it outright; the rename makes the file appear
 * atomically or not at all.
 *
 * <p>The server's host key is pinned when the target supplies one. Without pinning, the first
 * connection would trust whatever answers, and what is being handed over is every driver's
 * complete working record.
 */
@Singleton
public class SftpForwarder implements TachographForwarder {

    private static final Logger LOGGER = LoggerFactory.getLogger(SftpForwarder.class);

    private static final int DEFAULT_PORT = 22;
    private static final int CONNECT_TIMEOUT_MILLIS = 30_000;
    private static final int TRANSFER_TIMEOUT_MILLIS = 300_000;

    /** Suffix used while bytes are still arriving at the far end. */
    private static final String PARTIAL_SUFFIX = ".part";

    private final SshKeyLoader keyLoader;

    @Inject
    public SftpForwarder(SshKeyLoader keyLoader) {
        this.keyLoader = keyLoader;
    }

    @Override
    public String getTransport() {
        return TachographForwardTarget.TRANSPORT_SFTP;
    }

    @Override
    public void deliver(
            TachographForwardTarget target, ForwardCredentials credentials,
            Path localFile, String remoteName) throws ForwardException {

        try (SSHClient client = connect(target, credentials);
             SFTPClient sftp = client.newSFTPClient()) {

            String directory = normaliseDirectory(target.getRemotePath());
            ensureDirectory(sftp, directory);

            String finalPath = directory + remoteName;
            String partialPath = finalPath + PARTIAL_SUFFIX;

            sftp.put(new FileSystemFile(localFile.toFile()), partialPath);

            // Remove a leftover from an earlier attempt so the rename cannot fail on a name clash.
            try {
                sftp.rm(finalPath);
            } catch (IOException ignored) {
                // The usual case: the file is not there, which is exactly what we want.
            }
            sftp.rename(partialPath, finalPath);

            LOGGER.info("Delivered {} to {} at {}", remoteName, target.getName(), finalPath);

        } catch (ForwardException e) {
            throw e;
        } catch (IOException e) {
            throw classify(target, e);
        }
    }

    @Override
    public void test(TachographForwardTarget target, ForwardCredentials credentials)
            throws ForwardException {

        try (SSHClient client = connect(target, credentials);
             SFTPClient sftp = client.newSFTPClient()) {

            String directory = normaliseDirectory(target.getRemotePath());
            sftp.ls(directory.isEmpty() ? "." : directory);
            LOGGER.info("Tested the connection to {} successfully", target.getName());

        } catch (ForwardException e) {
            throw e;
        } catch (IOException e) {
            throw classify(target, e);
        }
    }

    // -----------------------------------------------------------------------
    // Connection
    // -----------------------------------------------------------------------

    private SSHClient connect(TachographForwardTarget target, ForwardCredentials credentials)
            throws ForwardException, IOException {

        if (target.getHost() == null || target.getHost().isBlank()) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Target " + target.getName() + " has no host name", false);
        }

        SSHClient client = new SSHClient();
        client.setConnectTimeout(CONNECT_TIMEOUT_MILLIS);
        client.setTimeout(TRANSFER_TIMEOUT_MILLIS);

        String pinnedKey = target.getHostKey();
        if (pinnedKey != null && !pinnedKey.isBlank()) {
            client.addHostKeyVerifier(new PinnedHostKeyVerifier(pinnedKey.trim()));
        } else {
            LOGGER.warn("Target {} has no pinned host key; the first server to answer will be "
                    + "trusted. Set a host key to protect driver data in transit.", target.getName());
            client.addHostKeyVerifier(new PromiscuousVerifier());
        }

        try {
            int port = target.getPort() > 0 ? target.getPort() : DEFAULT_PORT;
            client.connect(target.getHost(), port);
        } catch (TransportException e) {
            closeQuietly(client);
            throw new ForwardException(
                    ForwardException.ERROR_HOST_KEY,
                    "Host key check failed for " + target.getHost() + ": " + e.getMessage(), false, e);
        } catch (IOException e) {
            closeQuietly(client);
            throw new ForwardException(
                    ForwardException.ERROR_CONNECT,
                    "Could not reach " + target.getHost() + ": " + e.getMessage(), true, e);
        }

        try {
            authenticate(client, target, credentials);
        } catch (UserAuthException e) {
            closeQuietly(client);
            throw new ForwardException(
                    ForwardException.ERROR_AUTH,
                    "Authentication was refused by " + target.getHost()
                            + ". Check the username and credential.", false, e);
        } catch (IOException e) {
            closeQuietly(client);
            throw new ForwardException(
                    ForwardException.ERROR_CONNECT,
                    "Authentication to " + target.getHost() + " failed: " + e.getMessage(), true, e);
        }

        return client;
    }

    /**
     * Authenticates with a private key when the credential looks like one, otherwise a password.
     * Bureaux differ on which they issue, and an operator should not have to say which is which.
     */
    private void authenticate(
            SSHClient client, TachographForwardTarget target, ForwardCredentials credentials)
            throws IOException, ForwardException {

        String username = credentials.getUsername();
        if (username == null || username.isBlank()) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Target " + target.getName() + " has no user name", false);
        }
        if (!credentials.hasSecret()) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Target " + target.getName() + " has no stored credential", false);
        }

        if (keyLoader.looksLikePrivateKey(credentials.getSecret())) {
            KeyProvider keyProvider = keyLoader.load(credentials.getSecret());
            client.authPublickey(username, keyProvider);
        } else {
            client.authPassword(username, credentials.getSecret());
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    /** Creates the destination directory and every missing parent above it. */
    private void ensureDirectory(SFTPClient sftp, String directory) throws IOException {
        if (directory.isEmpty()) {
            return;
        }
        String trimmed = directory.endsWith("/")
                ? directory.substring(0, directory.length() - 1) : directory;
        try {
            sftp.stat(trimmed);
        } catch (IOException e) {
            sftp.mkdirs(trimmed);
        }
    }

    /** Normalises a remote directory to either empty or a path with a single trailing slash. */
    private String normaliseDirectory(String remotePath) {
        if (remotePath == null || remotePath.isBlank()) {
            return "";
        }
        String trimmed = remotePath.trim();
        return trimmed.endsWith("/") ? trimmed : trimmed + "/";
    }

    private ForwardException classify(TachographForwardTarget target, IOException cause) {
        return new ForwardException(
                ForwardException.ERROR_TRANSFER,
                "Transfer to " + target.getName() + " failed: " + cause.getMessage(), true, cause);
    }

    private void closeQuietly(SSHClient client) {
        try {
            client.close();
        } catch (IOException ignored) {
            // Nothing useful to do while already handling a failure.
        }
    }

    /**
     * Accepts only the host key the operator recorded for this target.
     *
     * <p>Accepts either a bare base64 key body or a full {@code ssh-rsa AAAA...} line, because
     * that is what a bureau's setup instructions usually paste as.
     */
    private static final class PinnedHostKeyVerifier implements HostKeyVerifier {

        private final String expected;

        private PinnedHostKeyVerifier(String expected) {
            this.expected = extractKeyBody(expected);
        }

        @Override
        public boolean verify(String hostname, int port, PublicKey key) {
            String actual = Base64.getEncoder().encodeToString(
                    new Buffer.PlainBuffer().putPublicKey(key).getCompactData());
            boolean matched = actual.equals(expected);
            if (!matched) {
                LOGGER.error("Host key mismatch for {}:{}. Expected the recorded key, got a "
                        + "different one; refusing to send tachograph data.", hostname, port);
            }
            return matched;
        }

        @Override
        public List<String> findExistingAlgorithms(String hostname, int port) {
            return List.of();
        }

        private static String extractKeyBody(String value) {
            String[] parts = value.trim().split("\\s+");
            for (String part : parts) {
                if (part.length() > 40 && !part.startsWith("ssh-") && !part.startsWith("ecdsa-")) {
                    return part;
                }
            }
            return parts[parts.length - 1];
        }
    }
}
