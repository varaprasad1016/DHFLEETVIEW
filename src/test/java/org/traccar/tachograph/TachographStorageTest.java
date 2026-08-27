package org.traccar.tachograph;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.traccar.config.Config;
import org.traccar.config.Keys;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class TachographStorageTest {

    @Test
    public void testPathTraversalRejected(@TempDir Path tempDir) throws IOException {
        Config config = mock(Config.class);
        when(config.getString(Keys.TACHO_STORAGE_PATH)).thenReturn(tempDir.toString());
        TachographStorage storage = new TachographStorage(config);

        assertThrows(IOException.class, () -> storage.resolveFinalPath(1, 2, "../evil.DDD"));
        assertThrows(IOException.class, () -> storage.resolveFinalPath(1, 2, "sub/evil.DDD"));
        assertThrows(IOException.class, () -> storage.resolveFinalPath(1, 2, "sub\\evil.DDD"));
    }

    @Test
    public void testValidPathAndSha256(@TempDir Path tempDir) throws IOException {
        Config config = mock(Config.class);
        when(config.getString(Keys.TACHO_STORAGE_PATH)).thenReturn(tempDir.toString());
        TachographStorage storage = new TachographStorage(config);

        Path finalPath = storage.resolveFinalPath(12, 54, "M_20260827_120000_54.DDD");
        assertTrue(finalPath.toString().contains("12"));
        assertTrue(finalPath.toString().contains("54"));

        Path tempFile = storage.createTempFile();
        byte[] data = "TEST_DDD_CONTENT".getBytes();
        storage.writeBytes(tempFile, data);
        String sha256 = storage.calculateSha256(tempFile);
        assertEquals(64, sha256.length());

        String sha256b = storage.calculateSha256(data);
        assertEquals(sha256, sha256b);

        storage.moveTempToFinal(tempFile, finalPath);
        assertTrue(Files.exists(finalPath));
        assertEquals(data.length, storage.fileSize(finalPath));
    }
}
