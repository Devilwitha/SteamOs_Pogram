package com.bollisoft.steamospico.data

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject

data class ApiResult(val ok: Boolean, val message: String)

class ApiException(message: String) : Exception(message)

/**
 * Spricht direkt mit den JSON-Routen von steamOs/gui/gui_server.py (API_ROUTES + /api/state) -
 * denselben Endpunkten, die auch Pico/control.html per fetch() nutzt, inklusive
 * X-Control-Token-Header fuer entfernte Clients (siehe Handler._is_authorized dort).
 */
class PicoApiClient(private val settingsProvider: () -> ConnectionSettings) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    private fun requestBuilder(path: String): Request.Builder {
        val s = settingsProvider()
        val builder = Request.Builder().url(s.baseUrl + path)
        if (s.token.isNotBlank()) builder.header("X-Control-Token", s.token)
        return builder
    }

    suspend fun getState(): Result<JSONObject> = withContext(Dispatchers.IO) {
        try {
            val request = requestBuilder("/api/state").get().build()
            client.newCall(request).execute().use { resp ->
                val bodyText = resp.body?.string() ?: "{}"
                if (!resp.isSuccessful) {
                    return@withContext Result.failure(ApiException(extractMessage(bodyText, resp.code)))
                }
                Result.success(JSONObject(bodyText))
            }
        } catch (e: IOException) {
            Result.failure(ApiException("PC nicht erreichbar (${e.message ?: "Netzwerkfehler"}) - IP/Port pruefen."))
        } catch (e: Exception) {
            Result.failure(ApiException("Ungueltige Antwort vom Server."))
        }
    }

    suspend fun post(path: String, body: JSONObject = JSONObject()): ApiResult = withContext(Dispatchers.IO) {
        try {
            val reqBody = body.toString().toRequestBody("application/json; charset=utf-8".toMediaType())
            val request = requestBuilder(path).post(reqBody).build()
            client.newCall(request).execute().use { resp -> parseResult(resp) }
        } catch (e: IOException) {
            ApiResult(false, "PC nicht erreichbar (${e.message ?: "Netzwerkfehler"}).")
        }
    }

    suspend fun postMultipart(
        path: String,
        fileField: String,
        fileName: String,
        bytes: ByteArray,
        mimeType: String,
        extraFields: Map<String, String> = emptyMap(),
    ): ApiResult = withContext(Dispatchers.IO) {
        try {
            val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
            extraFields.forEach { (key, value) -> multipart.addFormDataPart(key, value) }
            multipart.addFormDataPart(fileField, fileName, bytes.toRequestBody(mimeType.toMediaType()))
            val request = requestBuilder(path).post(multipart.build()).build()
            client.newCall(request).execute().use { resp -> parseResult(resp) }
        } catch (e: IOException) {
            ApiResult(false, "PC nicht erreichbar (${e.message ?: "Netzwerkfehler"}).")
        }
    }

    private fun parseResult(resp: Response): ApiResult {
        val bodyText = resp.body?.string() ?: "{}"
        return try {
            val json = JSONObject(bodyText)
            ApiResult(
                ok = json.optBoolean("ok", false),
                message = json.optString("message", if (resp.isSuccessful) "OK" else "Fehler (${resp.code})"),
            )
        } catch (e: Exception) {
            ApiResult(false, "Ungueltige Antwort vom Server (${resp.code}).")
        }
    }

    private fun extractMessage(bodyText: String, code: Int): String {
        return try {
            JSONObject(bodyText).optString("message", "Fehler ($code)")
        } catch (e: Exception) {
            if (code == 401) "Nicht autorisiert - Token pruefen." else "Fehler ($code)."
        }
    }
}
