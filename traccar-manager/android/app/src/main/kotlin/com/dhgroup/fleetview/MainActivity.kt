package com.dhgroup.fleetview

import android.content.ContentValues
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayInputStream
import java.io.File

/**
 * The app shell, plus one thing Flutter cannot do on its own: putting a file
 * the user downloaded somewhere they can find it again.
 *
 * Footage was being written into the app's own private folder and handed
 * straight to the share sheet, so a driver who wanted to keep a clip had to
 * send it somewhere else to keep it at all - and answering nothing kept
 * nothing. These go to the phone's real storage instead: video and photos
 * into the gallery (Movies / Pictures), everything else into Downloads, each
 * under a "DH FleetView" folder so a fleet's evidence is in one place.
 *
 * The file is copied from the path Flutter has already written rather than
 * passed through as bytes: a few minutes of footage is tens of megabytes and
 * there is no reason for it to sit in memory twice.
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
                        val path = call.argument<String>("path")
                        val name = call.argument<String>("name")
                        val mimeType = call.argument<String>("mimeType") ?: "application/octet-stream"
                        val bytes = call.argument<ByteArray>("bytes")
                        val source = path?.takeIf { it.isNotBlank() }?.let(::File)
                        if (name.isNullOrBlank() || (source == null && bytes == null)) {
                            result.error("bad_arguments", "A file path or file bytes and a name are required.", null)
                        } else {
                            try {
                                result.success(
                                    if (source != null) save(source, name, mimeType)
                                    else save(name, mimeType, bytes!!))
                            } catch (e: Exception) {
                                result.error("save_failed", e.message, null)
                            }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    /** Copies the file into shared storage and returns where to look for it. */
    private fun save(source: File, name: String, mimeType: String): String {
        if (!source.isFile) {
            throw IllegalArgumentException("That file is no longer there.")
        }
        return save(name, mimeType, source.inputStream())
    }

    private fun save(name: String, mimeType: String, bytes: ByteArray): String {
        return save(name, mimeType, ByteArrayInputStream(bytes))
    }

    private fun save(name: String, mimeType: String, source: java.io.InputStream): String {
        val kind = when {
            mimeType.startsWith("video/") -> Kind(Environment.DIRECTORY_MOVIES, "Movies")
            mimeType.startsWith("image/") -> Kind(Environment.DIRECTORY_PICTURES, "Pictures")
            else -> Kind(Environment.DIRECTORY_DOWNLOADS, "Downloads")
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // Scoped storage: the system owns the file and hands us a stream to
            // fill. Pending until it is written, so a half-copied clip never
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
            source.use { input ->
                contentResolver.openOutputStream(uri).use { out ->
                    if (out == null) {
                        throw IllegalStateException("The file could not be written.")
                    }
                    input.copyTo(out)
                }
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
            val target = File(directory, name)
            source.use { input ->
                target.outputStream().use { input.copyTo(it) }
            }
            MediaScannerConnection.scanFile(this, arrayOf(target.absolutePath), arrayOf(mimeType), null)
        }
        return "${kind.label}/$FOLDER"
    }

    private data class Kind(val directory: String, val label: String)
}
