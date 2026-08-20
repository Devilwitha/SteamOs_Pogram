package com.bollisoft.steamospico.data

import org.json.JSONObject

/** Verbindung zu steamOs/gui/gui_server.py auf dem PC (siehe Pico/control.html: dieselbe Idee,
 * nur nativ statt als vom Pico gehostete Webseite). */
data class ConnectionSettings(
    val ip: String,
    val port: Int,
    val token: String,
) {
    val baseUrl: String get() = "http://$ip:$port"
    val isConfigured: Boolean get() = ip.isNotBlank()
}

data class GameInfo(
    val uid: String,
    val name: String,
    val installed: Boolean,
    val color: String?,
    val hasAudio: Boolean,
    val audioName: String?,
    val audioEnabled: Boolean,
)

data class TagInfo(
    val uid: String,
    val gameUid: String?,
)

data class AppState(
    val appVersion: String?,
    val games: List<GameInfo>,
    val tags: List<TagInfo>,
    val picoReachable: Boolean,
    val audioMode: String,
    val hasBootSound: Boolean,
    val bootSoundName: String?,
    val hasVideo: Boolean,
    val videoName: String?,
    val ledEnabled: Boolean,
    val idleLedColor: String,
    val blinkOnSleep: Boolean,
    val downloadPulse: Boolean,
    val downloadGradientStart: String,
    val downloadGradientMid: String,
    val downloadGradientEnd: String,
    val downloadGradientEnabled: Boolean,
    val downloadActive: Boolean,
    val downloadProgress: Double?,
    val downloadName: String?,
)

/** Feste Farbpalette wie PALETTE in dashboard.html - per Controller/Touch zuverlaessig
 * bedienbar, statt eines echten Farbwaehlers. */
val COLOR_PALETTE = listOf(
    "#ff4d6d", "#ff8800", "#ffb238", "#ffe14d", "#39ff8c", "#00e5ff",
    "#0891a8", "#3b82f6", "#7c5cff", "#ff2e97", "#ffffff", "#7686a0",
)

const val AUDIO_MODE_SONGS = "songs"
const val AUDIO_MODE_BOOT_SOUND = "boot_sound"
const val AUDIO_MODE_VIDEO = "video"

val AUDIO_MODES = listOf(AUDIO_MODE_SONGS, AUDIO_MODE_BOOT_SOUND, AUDIO_MODE_VIDEO)

val AUDIO_MODE_LABELS = mapOf(
    AUDIO_MODE_SONGS to "Einzelne Songs je Spiel",
    AUDIO_MODE_BOOT_SOUND to "Ein Boot-Sound fuer alle Spiele",
    AUDIO_MODE_VIDEO to "Ein Video (Vollbild) fuer alle Spiele",
)

fun parseAppState(json: JSONObject): AppState {
    val gamesArr = json.optJSONArray("games")
    val games = buildList {
        if (gamesArr != null) {
            for (i in 0 until gamesArr.length()) {
                val g = gamesArr.getJSONObject(i)
                add(
                    GameInfo(
                        uid = g.optString("uid"),
                        name = g.optString("name"),
                        installed = g.optBoolean("installed", true),
                        color = g.optStringOrNull("color"),
                        hasAudio = g.optBoolean("has_audio", false),
                        audioName = g.optStringOrNull("audio_name"),
                        audioEnabled = g.optBoolean("audio_enabled", false),
                    )
                )
            }
        }
    }
    val tagsArr = json.optJSONArray("tags")
    val tags = buildList {
        if (tagsArr != null) {
            for (i in 0 until tagsArr.length()) {
                val t = tagsArr.getJSONObject(i)
                add(
                    TagInfo(
                        uid = t.optString("uid"),
                        gameUid = t.optStringOrNull("game_uid"),
                    )
                )
            }
        }
    }
    return AppState(
        appVersion = json.optStringOrNull("app_version"),
        games = games,
        tags = tags,
        picoReachable = json.optBoolean("pico_reachable", false),
        audioMode = json.optString("audio_mode", AUDIO_MODE_SONGS),
        hasBootSound = json.optBoolean("has_boot_sound", false),
        bootSoundName = json.optStringOrNull("boot_sound_name"),
        hasVideo = json.optBoolean("has_video", false),
        videoName = json.optStringOrNull("video_name"),
        ledEnabled = json.optBoolean("led_enabled", false),
        idleLedColor = json.optString("idle_led_color", "#ffffff"),
        blinkOnSleep = json.optBoolean("blink_on_sleep", false),
        downloadPulse = json.optBoolean("download_pulse", false),
        downloadGradientStart = json.optString("download_gradient_start", "#ff0000"),
        downloadGradientMid = json.optString("download_gradient_mid", "#ffff00"),
        downloadGradientEnd = json.optString("download_gradient_end", "#00ff00"),
        downloadGradientEnabled = json.optBoolean("download_gradient_enabled", false),
        downloadActive = json.optBoolean("download_active", false),
        downloadProgress = if (json.isNull("download_progress")) null else json.optDouble("download_progress").let {
            if (it.isNaN()) null else it
        },
        downloadName = json.optStringOrNull("download_name"),
    )
}

private fun JSONObject.optStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    val v = optString(key, "")
    return v.ifEmpty { null }
}
