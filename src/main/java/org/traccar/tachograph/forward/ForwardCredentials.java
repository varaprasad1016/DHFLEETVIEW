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

/**
 * A decrypted credential, held only for the length of one delivery.
 *
 * <p>Kept separate from the target model so the plaintext never sits on an object that gets
 * serialised, logged or returned by the API.
 */
public final class ForwardCredentials {

    private final String username;
    private final String secret;

    public ForwardCredentials(String username, String secret) {
        this.username = username;
        this.secret = secret;
    }

    public String getUsername() {
        return username;
    }

    /** The password, private key or API key, in plaintext. */
    public String getSecret() {
        return secret;
    }

    public boolean hasSecret() {
        return secret != null && !secret.isEmpty();
    }

    @Override
    public String toString() {
        // Never let a credential reach a log through an accidental string concatenation.
        return "ForwardCredentials[username=" + username + ", secret=***]";
    }
}
