package com.bollisoft.steamospico.ui.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.data.AUDIO_MODES
import com.bollisoft.steamospico.data.AUDIO_MODE_BOOT_SOUND
import com.bollisoft.steamospico.data.AUDIO_MODE_LABELS
import com.bollisoft.steamospico.data.AUDIO_MODE_VIDEO
import com.bollisoft.steamospico.data.FileUtils
import com.bollisoft.steamospico.data.GameInfo
import com.bollisoft.steamospico.data.TagInfo
import com.bollisoft.steamospico.ui.PicoViewModel
import com.bollisoft.steamospico.ui.components.ColorPickerDialog
import com.bollisoft.steamospico.ui.components.ColorSwatch
import com.bollisoft.steamospico.ui.components.GamePickerDialog
import com.bollisoft.steamospico.ui.components.RowSpec
import com.bollisoft.steamospico.ui.components.SettingRow
import com.bollisoft.steamospico.ui.components.shortUid
import com.bollisoft.steamospico.ui.jsonOf

/**
 * 1:1-Pendant zu index.html/admin (+ die Verbindungs-/Upload-Erweiterungen aus
 * Pico/control.html): volle Spiele-/Tag-Tabelle inklusive Sound-Uploads je Spiel sowie
 * Boot-Sound-/Video-Upload, die die Konsole (ConsoleScreen) bewusst nicht anbietet.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdminScreen(vm: PicoViewModel, modifier: Modifier = Modifier) {
    val settings by vm.settings.collectAsState()
    val state by vm.state.collectAsState()
    val connectionError by vm.connectionError.collectAsState()
    val context = LocalContext.current

    var colorDialogFor by remember { mutableStateOf<GameInfo?>(null) }
    var ledsColorRow by remember { mutableStateOf<RowSpec.ColorPick?>(null) }
    var tagPickerFor by remember { mutableStateOf<TagInfo?>(null) }
    var forgetConfirm by remember { mutableStateOf(false) }
    var resetConfirm by remember { mutableStateOf(false) }
    var pendingUploadGameUid by remember { mutableStateOf<String?>(null) }

    val gameAudioPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        val uid = pendingUploadGameUid
        pendingUploadGameUid = null
        if (uri != null && uid != null) {
            FileUtils.readBytes(context, uri)?.let { bytes ->
                vm.uploadFile(
                    "/api/set_game_audio", "audio_file", FileUtils.displayName(context, uri),
                    bytes, FileUtils.mimeType(context, uri), mapOf("uid" to uid),
                )
            }
        }
    }
    val bootSoundPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            FileUtils.readBytes(context, uri)?.let { bytes ->
                vm.uploadFile("/api/set_boot_sound", "boot_sound_file", FileUtils.displayName(context, uri), bytes, FileUtils.mimeType(context, uri))
            }
        }
    }
    val videoPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            FileUtils.readBytes(context, uri)?.let { bytes ->
                vm.uploadFile("/api/set_video", "video_file", FileUtils.displayName(context, uri), bytes, FileUtils.mimeType(context, uri))
            }
        }
    }

    Column(modifier = modifier.fillMaxSize()) {
        when {
            !settings.isConfigured -> CenteredMessage("Bitte zuerst unter \"Verbindung\" IP, Port und Token eintragen.")
            state == null -> {
                if (connectionError != null) {
                    CenteredMessage(connectionError ?: "PC nicht erreichbar.")
                } else {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                }
            }

            else -> {
                val s = state!!
                val gameNames = s.games.associate { it.uid to it.name }

                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { SectionTitle("Sound-Modus") }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            AUDIO_MODES.forEach { mode ->
                                FilterChip(
                                    selected = s.audioMode == mode,
                                    onClick = { vm.action("/api/set_audio_mode", jsonOf("mode" to mode)) },
                                    label = { Text(AUDIO_MODE_LABELS[mode] ?: mode) },
                                )
                            }
                        }
                    }
                    if (s.audioMode == AUDIO_MODE_BOOT_SOUND) {
                        item {
                            MediaCard(
                                title = "Boot-Sound",
                                fileName = s.bootSoundName,
                                onUpload = { bootSoundPicker.launch("audio/*") },
                                onPlay = { vm.action("/api/play_boot_sound") },
                                onStop = { vm.action("/api/stop_boot_sound") },
                                onRemove = { vm.action("/api/remove_boot_sound") },
                            )
                        }
                    }
                    if (s.audioMode == AUDIO_MODE_VIDEO) {
                        item {
                            MediaCard(
                                title = "Video",
                                fileName = s.videoName,
                                onUpload = { videoPicker.launch("video/*") },
                                onPlay = { vm.action("/api/play_video") },
                                onStop = { vm.action("/api/stop_video") },
                                onRemove = { vm.action("/api/remove_video") },
                            )
                        }
                    }

                    item { SectionTitle("LED-Einstellungen") }
                    item {
                        Card(modifier = Modifier.fillMaxWidth()) {
                            ledsRows(s, vm).forEach { row ->
                                SettingRow(row = row, onColorPickRequested = { ledsColorRow = it })
                            }
                        }
                    }

                    item {
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            SectionTitle("Spiele")
                            TextButton(onClick = { resetConfirm = true }) { Text("Farben zuruecksetzen...") }
                        }
                    }
                    if (s.games.isEmpty()) {
                        item { Text("Keine Spiele gefunden. Zuerst game_scanner.py ausfuehren.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    } else {
                        items(s.games, key = { it.uid }) { game ->
                            GameAdminCard(
                                game = game,
                                onColorClick = { colorDialogFor = game },
                                onToggleAudio = { enabled ->
                                    vm.action("/api/toggle_game_audio", jsonOf("uid" to game.uid, "enabled" to enabled))
                                },
                                onPlay = { vm.action("/api/play_game_audio", jsonOf("uid" to game.uid)) },
                                onStop = { vm.action("/api/stop_game_audio") },
                                onRemoveAudio = { vm.action("/api/remove_game_audio", jsonOf("uid" to game.uid)) },
                                onUpload = {
                                    pendingUploadGameUid = game.uid
                                    gameAudioPicker.launch("audio/*")
                                },
                            )
                        }
                    }

                    item {
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            SectionTitle("Bekannte RFID-Tags")
                            TextButton(onClick = { forgetConfirm = true }) { Text("Tag loeschen...") }
                        }
                    }
                    if (s.tags.isEmpty()) {
                        item { Text("Noch keine Tags erkannt. Einen Tag an den RC522 halten.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    } else {
                        items(s.tags, key = { it.uid }) { tag ->
                            TagAdminRow(
                                tag = tag,
                                linkedName = tag.gameUid?.let { gameNames[it] },
                                onLink = { tagPickerFor = tag },
                                onUnlink = { vm.action("/api/unlink_tag", jsonOf("uid" to tag.uid)) },
                            )
                        }
                    }
                }
            }
        }
    }

    colorDialogFor?.let { game ->
        ColorPickerDialog(
            title = "Farbe: ${game.name}",
            currentColor = game.color ?: "#7686a0",
            onPick = { hex ->
                vm.action("/api/set_game_color", jsonOf("uid" to game.uid, "color" to hex))
                colorDialogFor = null
            },
            onDismiss = { colorDialogFor = null },
        )
    }

    ledsColorRow?.let { row ->
        ColorPickerDialog(
            title = row.label,
            currentColor = row.color,
            onPick = { hex ->
                row.onSetColor(hex)
                ledsColorRow = null
            },
            onDismiss = { ledsColorRow = null },
        )
    }

    tagPickerFor?.let { tag ->
        state?.let { s ->
            val linkedElsewhere = s.tags
                .filter { it.gameUid != null && it.uid != tag.uid }
                .mapNotNull { it.gameUid }
                .toSet()
            GamePickerDialog(
                title = "Verknuepfen: ${shortUid(tag.uid)}",
                games = s.games.filter { it.uid !in linkedElsewhere },
                onPick = { game ->
                    vm.action("/api/link_tag", jsonOf("uid" to tag.uid, "game_uid" to game.uid))
                    tagPickerFor = null
                },
                onDismiss = { tagPickerFor = null },
            )
        }
    }

    if (forgetConfirm) {
        AlertDialog(
            onDismissRequest = { forgetConfirm = false },
            title = { Text("Tag loeschen") },
            text = {
                Text(
                    "Versetzt den Pico in den Loeschmodus. Danach den zu loeschenden Tag an den " +
                        "RC522 halten - er wird beim naechsten Erkennen komplett entfernt.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    forgetConfirm = false
                    vm.action("/api/forget_tag")
                }) { Text("Loeschmodus aktivieren") }
            },
            dismissButton = { TextButton(onClick = { forgetConfirm = false }) { Text("Abbrechen") } },
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
            dismissButton = { TextButton(onClick = { resetConfirm = false }) { Text("Abbrechen") } },
        )
    }
}

@Composable
private fun CenteredMessage(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary,
    )
}

@Composable
private fun MediaCard(
    title: String,
    fileName: String?,
    onUpload: () -> Unit,
    onPlay: () -> Unit,
    onStop: () -> Unit,
    onRemove: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(
                fileName ?: "Keine Datei hinterlegt - Upload unter /admin bzw. hier.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp, bottom = 10.dp),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onUpload) { Text("Hochladen") }
                if (fileName != null) {
                    OutlinedButton(onClick = onPlay) { Text("Abspielen") }
                    OutlinedButton(onClick = onStop) { Text("Stoppen") }
                    OutlinedButton(onClick = onRemove) { Text("Entfernen") }
                }
            }
        }
    }
}

@Composable
private fun GameAdminCard(
    game: GameInfo,
    onColorClick: () -> Unit,
    onToggleAudio: (Boolean) -> Unit,
    onPlay: () -> Unit,
    onStop: () -> Unit,
    onRemoveAudio: () -> Unit,
    onUpload: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .clickable { onColorClick() },
                ) {
                    ColorSwatch(game.color, size = 26.dp)
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(game.name, style = MaterialTheme.typography.titleSmall)
                        if (!game.installed) {
                            Text(
                                "  NICHT INSTALLIERT",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.tertiary,
                            )
                        }
                    }
                    Text(shortUid(game.uid), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(10.dp))
            if (game.hasAudio) {
                Text(game.audioName ?: "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    IconButton(onClick = onPlay) { Icon(Icons.Filled.PlayArrow, contentDescription = "Abspielen") }
                    IconButton(onClick = onStop) { Icon(Icons.Filled.Stop, contentDescription = "Stoppen") }
                    IconButton(onClick = onRemoveAudio) { Icon(Icons.Filled.Delete, contentDescription = "Entfernen") }
                    Spacer(Modifier.weight(1f))
                    Text(
                        if (game.audioEnabled) "Aktiv" else "Inaktiv",
                        style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(end = 6.dp),
                    )
                    Switch(checked = game.audioEnabled, onCheckedChange = onToggleAudio)
                }
            } else {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        "Kein Sound",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedButton(onClick = onUpload) {
                        Icon(Icons.Filled.UploadFile, contentDescription = null, modifier = Modifier.height(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Hochladen")
                    }
                }
            }
        }
    }
}

@Composable
private fun TagAdminRow(
    tag: TagInfo,
    linkedName: String?,
    onLink: () -> Unit,
    onUnlink: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(shortUid(tag.uid), style = MaterialTheme.typography.bodyMedium)
                Text(
                    linkedName ?: "nicht verknuepft",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (linkedName != null) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (linkedName != null) {
                IconButton(onClick = onUnlink) { Icon(Icons.Filled.LinkOff, contentDescription = "Trennen") }
            } else {
                IconButton(onClick = onLink) { Icon(Icons.Filled.Link, contentDescription = "Verknuepfen") }
            }
        }
    }
}
