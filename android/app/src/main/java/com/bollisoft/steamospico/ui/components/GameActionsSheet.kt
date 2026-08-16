package com.bollisoft.steamospico.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.data.GameInfo
import com.bollisoft.steamospico.ui.PicoViewModel
import com.bollisoft.steamospico.ui.jsonOf

/** Spiegelt openGameActions() in dashboard.html: Farbe, (falls vorhanden) Sound
 * an/aus + testen/stoppen, "Fuer naechsten Tag vormerken". Der Upload selbst bleibt wie im
 * Original der Verwaltungs-GUI vorbehalten (siehe AdminScreen). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GameActionsSheet(game: GameInfo, vm: PicoViewModel, onDismiss: () -> Unit) {
    var colorDialogFor by remember { mutableStateOf(false) }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(bottom = 24.dp)) {
            Text(
                "Spiel: ${game.name}",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )

            SettingRow(
                row = RowSpec.ColorPick("Farbe", game.color ?: "#7686a0", onSetColor = {}),
                onColorPickRequested = { colorDialogFor = true },
            )

            if (game.hasAudio) {
                SettingRow(
                    row = RowSpec.Toggle(
                        label = if (game.audioEnabled) "Sound: Aktiv" else "Sound: Inaktiv",
                        value = game.audioEnabled,
                        onToggle = {
                            vm.action(
                                "/api/toggle_game_audio",
                                jsonOf("uid" to game.uid, "enabled" to !game.audioEnabled),
                            )
                        },
                    ),
                    onColorPickRequested = {},
                )
                SettingRow(
                    row = RowSpec.Action("Sound testen (${game.audioName ?: ""})") {
                        vm.action("/api/play_game_audio", jsonOf("uid" to game.uid))
                    },
                    onColorPickRequested = {},
                )
                SettingRow(
                    row = RowSpec.Action("Wiedergabe stoppen") {
                        vm.action("/api/stop_game_audio")
                    },
                    onColorPickRequested = {},
                )
            } else {
                SettingRow(
                    row = RowSpec.Info("Kein Sound hinterlegt - Upload unter \"Verwaltung\"."),
                    onColorPickRequested = {},
                )
            }

            SettingRow(
                row = RowSpec.Action("Fuer naechsten Tag vormerken") {
                    vm.action("/api/select_game", jsonOf("uid" to game.uid)) { ok -> if (ok) onDismiss() }
                },
                onColorPickRequested = {},
            )
        }
    }

    if (colorDialogFor) {
        ColorPickerDialog(
            title = "Farbe: ${game.name}",
            currentColor = game.color ?: "#7686a0",
            onPick = { hex ->
                vm.action("/api/set_game_color", jsonOf("uid" to game.uid, "color" to hex))
                colorDialogFor = false
            },
            onDismiss = { colorDialogFor = false },
        )
    }
}
