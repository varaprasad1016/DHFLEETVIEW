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

import com.hierynomus.sshj.userauth.keyprovider.OpenSSHKeyV1KeyFile;

import net.schmizz.sshj.userauth.keyprovider.FileKeyProvider;
import net.schmizz.sshj.userauth.keyprovider.KeyFormat;
import net.schmizz.sshj.userauth.keyprovider.KeyProvider;
import net.schmizz.sshj.userauth.keyprovider.KeyProviderUtil;
import net.schmizz.sshj.userauth.keyprovider.OpenSSHKeyFile;
import net.schmizz.sshj.userauth.keyprovider.PKCS8KeyFile;

import jakarta.inject.Singleton;

import java.io.IOException;
import java.io.StringReader;

/**
 * Turns a stored SSH private key into something sshj can authenticate with.
 *
 * <p>Bureaux hand out keys in whichever format their tooling produced, so the format is detected
 * from the key text rather than asked for. Only unencrypted keys are supported: a passphrase on
 * the key would have to be stored next to it, which buys nothing over storing the key alone.
 */
@Singleton
public class SshKeyLoader {

    /**
     * Whether a stored credential is a private key rather than a password.
     */
    public boolean looksLikePrivateKey(String secret) {
        if (secret == null) {
            return false;
        }
        String trimmed = secret.trim();
        return trimmed.startsWith("-----BEGIN") && trimmed.contains("PRIVATE KEY");
    }

    /**
     * Parses a private key.
     *
     * @throws ForwardException when the key cannot be read, which is a configuration problem and
     *         is therefore never retried
     */
    public KeyProvider load(String privateKey) throws ForwardException {
        try {
            KeyFormat format = KeyProviderUtil.detectKeyFileFormat(privateKey, true);
            FileKeyProvider provider = switch (format) {
                case OpenSSH -> new OpenSSHKeyFile();
                case OpenSSHv1 -> new OpenSSHKeyV1KeyFile();
                case PKCS8 -> new PKCS8KeyFile();
                default -> throw new ForwardException(
                        ForwardException.ERROR_CONFIGURATION,
                        "Unsupported private key format: " + format, false);
            };
            provider.init(new StringReader(privateKey));
            return provider;

        } catch (IOException e) {
            throw new ForwardException(
                    ForwardException.ERROR_CONFIGURATION,
                    "Could not read the stored private key: " + e.getMessage(), false, e);
        }
    }
}
