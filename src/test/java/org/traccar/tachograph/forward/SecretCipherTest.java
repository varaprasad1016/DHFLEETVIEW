package org.traccar.tachograph.forward;

import org.junit.jupiter.api.Test;
import org.traccar.config.Config;
import org.traccar.config.Keys;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class SecretCipherTest {

    private SecretCipher cipherWith(String passphrase) {
        Config config = mock(Config.class);
        when(config.getString(Keys.TACHO_FORWARD_SECRET)).thenReturn(passphrase);
        return new SecretCipher(config);
    }

    @Test
    public void testRoundTrip() {
        SecretCipher cipher = cipherWith("a-long-configuration-passphrase");

        String secret = "sftp-password-with-symbols !@#£";
        String stored = cipher.encrypt(secret);

        assertNotEquals(secret, stored);
        assertEquals(secret, cipher.decrypt(stored));
    }

    @Test
    public void testCiphertextDiffersBetweenEncryptions() {
        SecretCipher cipher = cipherWith("a-long-configuration-passphrase");

        // A fresh initialisation vector each time means two identical credentials do not produce
        // identical rows, so the database never reveals which targets share a password.
        String first = cipher.encrypt("same-secret");
        String second = cipher.encrypt("same-secret");

        assertNotEquals(first, second);
        assertEquals("same-secret", cipher.decrypt(first));
        assertEquals("same-secret", cipher.decrypt(second));
    }

    @Test
    public void testBlankValuesArePassedThrough() {
        SecretCipher cipher = cipherWith("a-long-configuration-passphrase");

        assertNull(cipher.encrypt(null));
        assertNull(cipher.encrypt(""));
        assertNull(cipher.decrypt(null));
        assertNull(cipher.decrypt(""));
    }

    @Test
    public void testWrongPassphraseCannotDecrypt() {
        String stored = cipherWith("original-passphrase").encrypt("bureau-password");
        SecretCipher other = cipherWith("a-different-passphrase");

        // Changing tacho.forward.secret must not silently yield garbage: it has to fail loudly so
        // an operator knows the credentials need re-entering.
        assertThrows(IllegalStateException.class, () -> other.decrypt(stored));
    }

    @Test
    public void testTamperedCiphertextIsRejected() {
        SecretCipher cipher = cipherWith("a-long-configuration-passphrase");
        String stored = cipher.encrypt("bureau-password");

        byte[] raw = java.util.Base64.getDecoder().decode(stored);
        raw[raw.length - 1] ^= 0x01;
        String tampered = java.util.Base64.getEncoder().encodeToString(raw);

        assertThrows(IllegalStateException.class, () -> cipher.decrypt(tampered));
    }

    @Test
    public void testMissingPassphraseIsReported() {
        SecretCipher cipher = cipherWith(null);

        assertFalse(cipher.isConfigured());
        assertThrows(IllegalStateException.class, () -> cipher.encrypt("anything"));
    }

    @Test
    public void testConfiguredReportsPassphrasePresence() {
        assertTrue(cipherWith("set").isConfigured());
        assertFalse(cipherWith("   ").isConfigured());
    }
}
