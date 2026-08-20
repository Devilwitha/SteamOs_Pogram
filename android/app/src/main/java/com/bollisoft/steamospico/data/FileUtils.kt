package com.bollisoft.steamospico.data

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns

object FileUtils {

    fun readBytes(context: Context, uri: Uri): ByteArray? = try {
        context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
    } catch (e: Exception) {
        null
    }

    fun displayName(context: Context, uri: Uri): String {
        var name: String? = null
        try {
            context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && cursor.moveToFirst()) name = cursor.getString(idx)
            }
        } catch (e: Exception) {
            // ignoriert - Fallback unten
        }
        return name ?: uri.lastPathSegment ?: "datei"
    }

    fun mimeType(context: Context, uri: Uri): String =
        context.contentResolver.getType(uri) ?: "application/octet-stream"
}
