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

import org.traccar.config.Config;
import org.traccar.config.Keys;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;

/**
 * Encrypts the credentials used to reach analysis bureaux.
 *
 * <p>A bureau password or API key sits in the database next to the files it unlocks, so storing
 * it in plaintext would mean a single read of one table is enough to exfiltrate a fleet's entire
 * driver-hours record. It is encrypted with AES-GCM under a key derived from
 * {@code tacho.forward.secret}, which lives in the configuration file rather than the database,
 * so compromising one is not enough.
 *
 * <p>Changing {@code tacho.forward.secret} makes every stored credential unreadable; they must
 * then be entered again.
 */
@Singleton
public class SecretCipher {

    private static final String KEY_ALGORITHM = "AES";
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final String DERIVATION_ALGORITHM = "PBKDF2WithHmacSHA256";

    private static final int KEY_BITS = 256;
    private static final int ITERATIONS = 210_000;
    private static final int IV_BYTES = 12;
    private static final int TAG_BITS = 128;

    /**
     * A fixed derivation salt. A per-record salt would be better in isolation, but the value
     * being protected is a configuration secret rather than a user password: it is high entropy,
     * there is one of it, and it is not reused elsewhere, so the salt's job here is only to keep
     * the derived key specific to this application.
     */
    private static final byte[] SALT = "dhfleetview.tachograph.forward".getBytes(StandardCharsets.UTF_8);

    private final Config config;
    private final SecureRandom random = new SecureRandom();

    private volatile SecretKey cachedKey;
    private volatile String cachedPassphrase;

    @Inject
    public SecretCipher(Config config) {
        this.config = config;
    }

    /** Whether a passphrase is configured, and so whether credentials can be stored at all. */
    public boolean isConfigured() {
        String passphrase = config.getString(Keys.TACHO_FORWARD_SECRET);
        return passphrase != null && !passphrase.isBlank();
    }

    /**
     * Encrypts a credential for storage.
     *
     * @return base64 of the initialisation vector followed by the ciphertext, or null for blank input
     * @throws IllegalStateException when no passphrase is configured
     */
    public String encrypt(String plaintext) {
        if (plaintext == null || plaintext.isEmpty()) {
            return null;
        }
        try {
            byte[] iv = new byte[IV_BYTES];
            random.nextBytes(iv);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, key(), new GCMParameterSpec(TAG_BITS, iv));
            byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));

            byte[] combined = new byte[iv.length + ciphertext.length];
            System.arraycopy(iv, 0, combined, 0, iv.length);
            System.arraycopy(ciphertext, 0, combined, iv.length, ciphertext.length);
            return Base64.getEncoder().encodeToString(combined);

        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("Could not encrypt the forwarding credential", e);
        }
    }

    /**
     * Decrypts a stored credential.
     *
     * @throws IllegalStateException when the passphrase is wrong or the value has been tampered with
     */
    public String decrypt(String stored) {
        if (stored == null || stored.isEmpty()) {
            return null;
        }
        try {
            byte[] combined = Base64.getDecoder().decode(stored);
            if (combined.length <= IV_BYTES) {
                throw new IllegalStateException("Stored credential is too short to be valid");
            }
            byte[] iv = Arrays.copyOfRange(combined, 0, IV_BYTES);
            byte[] ciphertext = Arrays.copyOfRange(combined, IV_BYTES, combined.length);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(TAG_BITS, iv));
            return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);

        } catch (GeneralSecurityException | IllegalArgumentException e) {
            throw new IllegalStateException(
                    "Could not decrypt a forwarding credential. If tacho.forward.secret was changed, "
                            + "the credential must be entered again.", e);
        }
    }

    private SecretKey key() {
        String passphrase = config.getString(Keys.TACHO_FORWARD_SECRET);
        if (passphrase == null || passphrase.isBlank()) {
            throw new IllegalStateException(
                    "tacho.forward.secret is not set. Set it in the configuration file before "
                            + "configuring a forwarding target.");
        }
        SecretKey key = cachedKey;
        if (key != null && passphrase.equals(cachedPassphrase)) {
            return key;
        }
        try {
            SecretKeyFactory factory = SecretKeyFactory.getInstance(DERIVATION_ALGORITHM);
            PBEKeySpec spec = new PBEKeySpec(passphrase.toCharArray(), SALT, ITERATIONS, KEY_BITS);
            key = new SecretKeySpec(factory.generateSecret(spec).getEncoded(), KEY_ALGORITHM);
            cachedKey = key;
            cachedPassphrase = passphrase;
            return key;
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("Could not derive the forwarding encryption key", e);
        }
    }
}
