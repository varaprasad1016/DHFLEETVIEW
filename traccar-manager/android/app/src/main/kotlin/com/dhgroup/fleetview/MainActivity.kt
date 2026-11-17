package com.dhgroup.fleetview

import android.content.ContentValues
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * The app shell, plus one thing Flutter cannot do on its own: putting a file
 * the user downloaded somewhere they can find it again.
 *
 * Footage used to be written into the app's own private folder and handed
 * straight to the share sheet, so a driver who wanted to keep a clip had to
 * send it somewhere to keep it. These go to the phone's real storage instead:
 * video and photos into the gallery (Movies / Pictures), everything else into
 * Downloads, each under a "DH FleetView" folder so a fleet's evidence is in
 * one place.
 */
class MainActivity : FlutterFragmentActivity() {

    private companion object {
        const val CHANNEL = "dhfleetview/storage"
        const val FOLDER = "DH FleetView"
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "save" -> {
                        val name = call.argument<String>("name")
                        val mimeType = call.argument<String>("mimeType") ?: "application/octet-stream"
                        val bytes = call.argument<ByteArray>("bytes")
                        if (name.isNullOrBlank() || bytes == null) {
                            result.error("bad_arguments", "A name and the file's bytes are required.", null)
                        } else {
                            try {
                                result.success(save(name, mimeType, bytes))
                            } catch (e: Exception) {
                                result.error("save_failed", e.message, null)
                            }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    /** Writes the file and returns where a person would look for it. */
    private fun save(name: String, mimeType: String, bytes: ByteArray): String {
        val kind = when {
            mimeType.startsWith("video/") -> Kind(Environment.DIRECTORY_MOVIES, "Movies")
            mimeType.startsWith("image/") -> Kind(Environment.DIRECTORY_PICTURES, "Pictures")
            else -> Kind(Environment.DIRECTORY_DOWNLOADS, "Downloads")
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // Scoped storage: the system owns the file, we are handed a stream
            // to fill. Pending until it is written, so nothing half-copied ever
            // shows up in the gallery.
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, name)
                put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
                put(MediaStore.MediaColumns.RELATIVE_PATH, "${kind.directory}/$FOLDER")
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            // Worked out here rather than above: MediaStore.Downloads only
            // exists from Android 10, and the branch below must not touch it.
            val collection = when (kind.directory) {
                Environment.DIRECTORY_MOVIES ->
                    MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                Environment.DIRECTORY_PICTURES ->
                    MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                else -> MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            }
            val uri = contentResolver.insert(collection, values)
                ?: throw IllegalStateException("The phone would not accept the file.")
            contentResolver.openOutputStream(uri).use { stream ->
                stream?.write(bytes) ?: throw IllegalStateException("The file could not be written.")
            }
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            contentResolver.update(uri, values, null, null)
        } else {
            // Before scoped storage a file is just a file, but nothing sees it
            // until the media scanner has been told.
            val directory = File(Environment.getExternalStoragePublicDirectory(kind.directory), FOLDER)
            if (!directory.exists() && !directory.mkdirs()) {
                throw IllegalStateException("The folder could not be created.")
            }
            val file = File(directory, name)
            file.writeBytes(bytes)
            MediaScannerConnection.scanFile(this, arrayOf(file.absolutePath), arrayOf(mimeType), null)
        }
        return "${kind.label}/$FOLDER"
    }

    private data class Kind(val directory: String, val label: String)
}
