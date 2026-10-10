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

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.model.TachographForwardTarget;

import jakarta.inject.Singleton;

import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Base64;
import java.util.List;
import java.util.Random;

/**
 * Delivers DDD files by HTTPS upload, for bureaux that offer an API instead of an SFTP drop.
 *
 * <p>The file is sent as a {@code multipart/form-data} POST with the DDD bytes in a {@code file}
 * part and the record's identifying fields alongside it, which is the shape almost every upload
 * endpoint expects. Authentication is a bearer token when the credential is an API key, or HTTP
 * basic when a user name is also set.
 *
 * <p>A 4xx answer other than 408 or 429 is treated as permanent: the bureau has looked at the
 * request and refused it, and sending the same bytes again tomorrow will get the same answer.
 */
@Singleton
public class HttpsForwarder implements TachographForwarder {

    private static final Logger LOGGER = LoggerFactory.getLogger(HttpsForwarder.class);

    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(30);
    private static final Duration REQUEST_TIMEOUT = Duration.ofMinutes(10);

    private static final int HTTP_REQUEST_TIMEOUT = 408;
    private static final int HTTP_TOO_MANY_REQUESTS = 429;

    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(CONNECT_TIMEOUT)
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    @Override
    public String getTransport() {
        return TachographForwardTarget.TRANSPORT_HTTPS;
    }

    @Override
    public void deliver(
            TachographForwardTarget target, ForwardCredentials credentials,
            Path localFile, String remoteName) throws ForwardException {

        URI uri = parseUrl(target);
        String boundary = "dhfv" + Long.toHexString(new Random().nextLong());

        try {
            byte[] body = buildMultipartBody(boundary, remoteName, Files.readAllBytes(localFile));

            HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
                    .timeout(REQUEST_TIMEOUT)
                    .header("Content-Type", "multipart/form-data; boundary=" + boundary)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body));
            applyAuthentication(builder, credentials);

            HttpResponse<String> response =
                    client.send(builder.build(), HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() / 100 != 2) {
                throw classifyStatus(target, response.statusCode(), response.body());
            }
            LOGGER.info("Delivered {} to {} ({})", remoteName, target.getName(), response.statusCode());

        } catch (IOException e) {
            throw new ForwardException(
                    ForwardException.ERROR_CONNECT,
                    "Could not reach " + uri.getHost() + ": " + e.getMessage(), true, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ForwardException(
                    ForwardException.ERROR_TRANSFER, "Delivery was interrupted", true, e);
        }
    }

    @Override
    public void test(TachographForwardTarget target, ForwardCredentials credentials)
            throws ForwardException {

        URI uri = parseUrl(target);
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(30))
                    .method("HEAD", HttpRequest.BodyPublishers.noBody());
            applyAuthentication(builder, credentials);

            HttpResponse<Void> response =
                    client.send(builder.build(), HttpResponse.BodyHandlers.discarding());

            // Many upload endpoints do not implement HEAD; anything that is not an
            // authentication failure means the endpoint is reachable and the credential works.
            if (response.statusCode() == 401 || response.statusCode() == 403) {
                throw new ForwardException(
                        ForwardException.ERROR_AUTH,
                        "The endpoint refused the stored credential (HTTP "
                                + response.statusCode() + ")", false);
            }
            LOGGER.info("Tested {} successfully (HTTP {})", target.getName(), response.statusCode());

        } catch (IOException e) {
            throw new ForwardException(
                    ForwardException.ERROR_CONNECT,
                    "Could not reach " + uri.getHost() + ": " + e.getMessage(), true, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ForwardException(
                    ForwardException.ERROR_TRANSFER, "The test was interrupted", true, e);
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private URI parseUrl(TachographForwardTarget target) throws ForwardException {
        String url = target.getUrl();
        if (url == null || url.isBlank()) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Target " + target.getName() + " has no endpoint URL", false);
        }
        try {
            URI uri = new URI(url.trim());
            if (!"https".equalsIgnoreCase(uri.getScheme())) {
                throw new ForwardException(
                        ForwardException.ERROR_CONFIGURATION,
                        "Target " + target.getName() + " must use https: driver hours data is "
                                + "personal data and must not travel in clear text", false);
            }
            return uri;
        } catch (URISyntaxException e) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Target " + target.getName() + " has an invalid URL: " + e.getMessage(), false, e);
        }
    }

    private void applyAuthentication(HttpRequest.Builder builder, ForwardCredentials credentials) {
        if (!credentials.hasSecret()) {
            return;
        }
        String username = credentials.getUsername();
        if (username != null && !username.isBlank()) {
            String encoded = Base64.getEncoder().encodeToString(
                    (username + ":" + credentials.getSecret()).getBytes(StandardCharsets.UTF_8));
            builder.header("Authorization", "Basic " + encoded);
        } else {
            builder.header("Authorization", "Bearer " + credentials.getSecret());
        }
    }

    /** Builds a multipart body with the file and the fields that identify it. */
    private byte[] buildMultipartBody(String boundary, String remoteName, byte[] content) {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();

        writeAscii(out, "--" + boundary + "\r\n");
        writeAscii(out, "Content-Disposition: form-data; name=\"fileName\"\r\n\r\n");
        writeAscii(out, remoteName + "\r\n");

        writeAscii(out, "--" + boundary + "\r\n");
        writeAscii(out, "Content-Disposition: form-data; name=\"file\"; filename=\"" + remoteName + "\"\r\n");
        writeAscii(out, "Content-Type: application/octet-stream\r\n\r\n");
        out.writeBytes(content);
        writeAscii(out, "\r\n");

        writeAscii(out, "--" + boundary + "--\r\n");
        return out.toByteArray();
    }

    private void writeAscii(java.io.ByteArrayOutputStream out, String text) {
        byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
        out.write(bytes, 0, bytes.length);
    }

    /**
     * Decides whether an HTTP failure is worth retrying. Server errors and the two "come back
     * later" client codes are; a refusal the bureau has already considered is not.
     */
    private ForwardException classifyStatus(TachographForwardTarget target, int status, String body) {
        String detail = body != null && body.length() > 300 ? body.substring(0, 300) : body;
        boolean retryable = status >= 500
                || status == HTTP_REQUEST_TIMEOUT
                || status == HTTP_TOO_MANY_REQUESTS;

        String code = List.of(401, 403).contains(status)
                ? ForwardException.ERROR_AUTH : ForwardException.ERROR_REJECTED;

        return new ForwardException(code, String.format(
                "%s rejected the upload with HTTP %d: %s", target.getName(), status, detail), retryable);
    }
}
