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

import org.traccar.model.TachographForwardTarget;

import java.nio.file.Path;

/**
 * Delivers one DDD file to one analysis bureau.
 *
 * <p>Implementations are stateless and are chosen by the target's transport, so adding a bureau
 * that accepts files a different way means adding one class rather than touching the queue.
 */
public interface TachographForwarder {

    /** The transport this forwarder handles, matching {@code TachographForwardTarget.TRANSPORT_*}. */
    String getTransport();

    /**
     * Sends one file.
     *
     * @param target     where to send it, with its credential already decrypted into
     *                   {@link ForwardCredentials}
     * @param localFile  the file on disk; it is never modified
     * @param remoteName the name to store it under at the far end
     * @throws ForwardException when delivery failed. Use
     *         {@link ForwardException#isRetryable()} to distinguish a network blip from a
     *         rejected credential, which no amount of retrying will fix.
     */
    void deliver(
            TachographForwardTarget target, ForwardCredentials credentials,
            Path localFile, String remoteName) throws ForwardException;

    /**
     * Checks the target is reachable and the credential works, without sending a file. Used by
     * the "test connection" button so an operator finds out at configuration time rather than
     * when the first legally required file fails to arrive.
     */
    void test(TachographForwardTarget target, ForwardCredentials credentials) throws ForwardException;
}
