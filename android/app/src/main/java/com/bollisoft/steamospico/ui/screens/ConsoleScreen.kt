package com.bollisoft.steamospico.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Nfc
import androidx.compose.material.icons.filled.SportsEsports
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.data.AUDIO_MODES
import com.bollisoft.steamospico.data.AUDIO_MODE_BOOT_SOUND
import com.bollisoft.steamospico.data.AUDIO_MODE_LABELS
import com.bollisoft.steamospico.data.AUDIO_MODE_VIDEO
import com.bollisoft.steamospico.data.AppState
import com.bollisoft.steamospico.data.GameInfo
import com.bollisoft.steamospico.data.TagInfo
import com.bollisoft.steamospico.ui.PicoViewModel
import com.bollisoft.steamospico.ui.components.ColorPickerDialog
import com.bollisoft.steamospico.ui.components.GameActionsSheet
import com.bollisoft.steamospico.ui.components.RowSpec
import com.bollisoft.steamospico.ui.components.SettingRow
import com.bollisoft.steamospico.ui.components.TagActionsSheet
import com.bollisoft.steamospico.ui.components.shortUid
import com.bollisoft.steamospico.ui.jsonOf

private data class Category(val id: String, val label: String, val icon: ImageVector)

private val CATEGORIES = listOf(
    Category("leds", "LEDs", Icons.Filled.Lightbulb),
    Category("sound", "Sound", Icons.Filled.MusicNote),
    Category("games", "Spiele", Icons.Filled.SportsEsports),
    Category("tags", "Tags", Icons.Filled.Nfc),
    Category("tools", "Werkzeuge", Icons.Filled.Build),
    Category("info", "Info", Icons.Filled.Info),
)

/**
 * 1:1-Pendant zu dashboard.html: dieselben sechs Kategorien (LEDs/Sound/Spiele/Tags/
 * Werkzeuge/Info), gefuellt aus /api/state und bedient ueber dieselben /api/...-Routen.
 * Datei-Uploads bleiben - wie im Original - dem Verwaltungs-Screen vorbehalten.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConsoleScreen(vm: PicoViewModel, modifier: Modifier = Modifier) {
    val settings by vm.settings.collectAsState()
    val state by vm.state.collectAsState()
    val connectionError by vm.connectionError.collectAsState()

    var categoryIndex by remember { mutableStateOf(0) }
    var selectedGame by remember { mutableStateOf<GameInfo?>(null) }
    var selectedTag by remember { mutableStateOf<TagInfo?>(null) }
    var colorDialogRow by remember { mutableStateOf<RowSpec.ColorPick?>(null) }
    var resetConfirm by remember { mutableStateOf(false) }

    Column(modifier = modifier.fillMaxSize()) {
        when {
            !settings.isConfigured -> CenteredHint(
                "Bitte zuerst unter \"Verbindung\" IP, Port und Token von gui_server.py eintragen.",
            )

            state == null -> {
                if (connectionError != null) {
                    CenteredHint(connectionError ?: "PC nicht erreichbar.")
                } else {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                }
            }

            else -> {
                val s = state!!

                if (s.downloadActive && s.downloadProgress != null) {
                    DownloadBar(progress = s.downloadProgress, name = s.downloadName)
                }

                ScrollableTabRow(selectedTabIndex = categoryIndex, edgePadding = 8.dp) {
                    CATEGORIES.forEachIndexed { i, cat ->
                        Tab(
                            selected = i == categoryIndex,
                            onClick = { categoryIndex = i },
                            text = { Text(cat.label) },
                            icon = { Icon(cat.icon, contentDescription = null) },
                        )
                    }
                }

                val rows = when (CATEGORIES[categoryIndex].id) {
                    "leds" -> ledsRows(s, vm)
                    "sound" -> soundRows(s, vm)
                    "games" -> gamesRows(s) { g -> selectedGame = g }
                    "tags" -> tagsRows(s) { t -> selectedTag = t }
                    "tools" -> toolsRows { resetConfirm = true }
                    else -> infoRows(s)
                }

                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    contentPadding = PaddingValues(bottom = 24.dp),
                ) {
                    items(rows) { row ->
                        SettingRow(row = row, onColorPickRequested = { colorDialogRow = it })
                    }
                }
            }
        }
    }

    selectedGame?.let { game ->
        GameActionsSheet(game = game, vm = vm, onDismiss = { selectedGame = null })
    }
    selectedTag?.let { tag ->
        state?.let { s -> TagActionsSheet(tag = tag, state = s, vm = vm, onDismiss = { selectedTag = null }) }
    }
    colorDialogRow?.let { row ->
        ColorPickerDialog(
            title = row.label,
            currentColor = row.color,
            onPick = { hex ->
                row.onSetColor(hex)
                colorDialogRow = null
            },
            onDismiss = { colorDialogRow = null },
        )
    }
    if (resetConfirm) {
        AlertDialog(
            onDismissRequest = { resetConfirm = false },
            title = { Text("Farben zuruecksetzen") },
            text = {
                Text(
                    "Wirklich ALLE Spielfarben auf ihre Cover-Durchschnittsfarbe zuruecksetzen? " +
                        "Das ueberschreibt auch manuell gesetzte Farben.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    resetConfirm = false
                    vm.action("/api/reset_all_colors")
                }) { Text("Zuruecksetzen") }
            },
            dismissButton = {
                TextButton(onClick = { resetConfirm = false }) { Text("Abbrechen") }
            },
        )
    }
}

@Composable
private fun CenteredHint(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, textAlign = androidx.compose.ui.text.style.TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun DownloadBar(progress: Double?, name: String?) {
    val pct = ((progress ?: 0.0).coerceIn(0.0, 1.0) * 100).toInt()
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text((name ?: "Download") + " · $pct%", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LinearProgressIndicator(
            progress = { (progress ?: 0.0).toFloat().coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        )
    }
}

/** Wird auch von AdminScreen wiederverwendet - beide Web-Originale (dashboard.html UND
 * index.html/admin) zeigen dieselben LED-Einstellungen. */
fun ledsRows(s: AppState, vm: PicoViewModel): List<RowSpec> = listOf(
    RowSpec.Toggle("LED-Synchronisation", s.ledEnabled) {
        vm.action("/api/set_led_enabled", jsonOf("enabled" to !s.ledEnabled))
    },
    RowSpec.ColorPick("Leerlauf-Farbe (\"Konsole an\")", s.idleLedColor) { hex ->
        vm.action("/api/set_idle_led_color", jsonOf("color" to hex))
    },
    RowSpec.Toggle("Blinken bei Sleep/Shutdown", s.blinkOnSleep) {
        vm.action("/api/set_blink_on_sleep", jsonOf("enabled" to !s.blinkOnSleep))
    },
    RowSpec.Toggle("Download-Pulsieren", s.downloadPulse) {
        vm.action("/api/set_download_pulse", jsonOf("enabled" to !s.downloadPulse))
    },
    RowSpec.Toggle("Farbverlauf im Leerlauf", s.downloadGradientEnabled) {
        vm.action("/api/set_download_gradient_enabled", jsonOf("enabled" to !s.downloadGradientEnabled))
    },
    RowSpec.ColorPick("Verlauf-Startfarbe (0%)", s.downloadGradientStart) { hex ->
        vm.action("/api/set_download_gradient_start", jsonOf("color" to hex))
    },
    RowSpec.ColorPick("Verlauf-Mittelfarbe (50%)", s.downloadGradientMid) { hex ->
        vm.action("/api/set_download_gradient_mid", jsonOf("color" to hex))
    },
    RowSpec.ColorPick("Verlauf-Endfarbe (100%)", s.downloadGradientEnd) { hex ->
        vm.action("/api/set_download_gradient_end", jsonOf("color" to hex))
    },
)

private fun soundRows(s: AppState, vm: PicoViewModel): List<RowSpec> {
    val rows = mutableListOf<RowSpec>(
        RowSpec.Enum("Sound-Modus", AUDIO_MODE_LABELS[s.audioMode] ?: s.audioMode) {
            val idx = AUDIO_MODES.indexOf(s.audioMode)
            val next = AUDIO_MODES[(idx + 1).mod(AUDIO_MODES.size)]
            vm.action("/api/set_audio_mode", jsonOf("mode" to next))
        },
    )
    when (s.audioMode) {
        AUDIO_MODE_BOOT_SOUND -> {
            if (s.hasBootSound) {
                rows += RowSpec.Action("▶ Boot-Sound abspielen (${s.bootSoundName})") { vm.action("/api/play_boot_sound") }
                rows += RowSpec.Action("■ Wiedergabe stoppen") { vm.action("/api/stop_boot_sound") }
            } else {
                rows += RowSpec.Info("Kein Boot-Sound hinterlegt - Upload unter \"Verwaltung\".")
            }
        }

        AUDIO_MODE_VIDEO -> {
            if (s.hasVideo) {
                rows += RowSpec.Action("▶ Video abspielen (${s.videoName})") { vm.action("/api/play_video") }
                rows += RowSpec.Action("■ Wiedergabe stoppen") { vm.action("/api/stop_video") }
            } else {
                rows += RowSpec.Info("Kein Video hinterlegt - Upload unter \"Verwaltung\".")
            }
        }

        else -> rows += RowSpec.Info("Sound pro Spiel: siehe Kategorie \"Spiele\".")
    }
    return rows
}

private fun gamesRows(s: AppState, onOpen: (GameInfo) -> Unit): List<RowSpec> {
    if (s.games.isEmpty()) {
        return listOf(RowSpec.Info("Keine Spiele gefunden. Zuerst game_scanner.py ausfuehren."))
    }
    return s.games.map { g ->
        RowSpec.ListEntry(
            label = g.name,
            color = g.color,
            badge = if (!g.installed) "nicht installiert" else null,
            subtext = if (g.hasAudio) "Sound: " + (if (g.audioEnabled) "aktiv" else "inaktiv") else "Kein Sound",
            dimmed = !g.installed,
            onClick = { onOpen(g) },
        )
    }
}

private fun tagsRows(s: AppState, onOpen: (TagInfo) -> Unit): List<RowSpec> {
    if (s.tags.isEmpty()) {
        return listOf(RowSpec.Info("Noch keine Tags erkannt. Einen Tag an den RC522 halten."))
    }
    val gameNames = s.games.associate { it.uid to it.name }
    val gameColors = s.games.associate { it.uid to it.color }
    return s.tags.map { t ->
        RowSpec.ListEntry(
            label = shortUid(t.uid),
            color = t.gameUid?.let { gameColors[it] } ?: "#7686a0",
            subtext = if (t.gameUid != null) "→ " + (gameNames[t.gameUid] ?: t.gameUid) else "nicht verknuepft",
            onClick = { onOpen(t) },
        )
    }
}

private fun toolsRows(onReset: () -> Unit): List<RowSpec> = listOf(
    RowSpec.Action("Farben zuruecksetzen...", onClick = onReset),
)

private fun infoRows(s: AppState): List<RowSpec> = listOf(
    RowSpec.Stat("Version", s.appVersion ?: "–"),
    RowSpec.Stat("Pico erreichbar", if (s.picoReachable) "Ja" else "Nein"),
    RowSpec.Stat("Hersteller", "BolliSoft"),
    RowSpec.Stat("Code", "Nico Bollhalder"),
)
