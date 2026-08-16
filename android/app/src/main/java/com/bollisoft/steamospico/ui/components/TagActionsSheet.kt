package com.bollisoft.steamospico.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.data.AppState
import com.bollisoft.steamospico.data.TagInfo
import com.bollisoft.steamospico.ui.PicoViewModel
import com.bollisoft.steamospico.ui.jsonOf

fun shortUid(uid: String): String =
    if (uid.length > 14) uid.take(6) + "…" + uid.takeLast(4) else uid

/** Spiegelt openTagActions() + openGamePicker() in dashboard.html: verknuepfen, trennen,
 * loeschen (Loeschmodus - der eigentliche Tag muss danach am RC522 vorgelegt werden). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TagActionsSheet(tag: TagInfo, state: AppState, vm: PicoViewModel, onDismiss: () -> Unit) {
    var showGamePicker by remember { mutableStateOf(false) }
    var showForgetConfirm by remember { mutableStateOf(false) }

    val linkedGameName = tag.gameUid?.let { uid -> state.games.firstOrNull { it.uid == uid }?.name }
    val linkedElsewhere = state.tags
        .filter { it.gameUid != null && it.uid != tag.uid }
        .mapNotNull { it.gameUid }
        .toSet()
    val pickableGames = state.games.filter { it.uid !in linkedElsewhere }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(bottom = 24.dp)) {
            Text(
                "Tag: ${shortUid(tag.uid)}",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
            SettingRow(
                row = RowSpec.Info(
                    if (linkedGameName != null) "Verknuepft mit: $linkedGameName" else "Nicht verknuepft",
                ),
                onColorPickRequested = {},
            )
            SettingRow(
                row = RowSpec.Action("Verknuepfen mit...") { showGamePicker = true },
                onColorPickRequested = {},
            )
            if (tag.gameUid != null) {
                SettingRow(
                    row = RowSpec.Action("Trennen") {
                        vm.action("/api/unlink_tag", jsonOf("uid" to tag.uid)) { onDismiss() }
                    },
                    onColorPickRequested = {},
                )
            }
            SettingRow(
                row = RowSpec.Action("Loeschen...") { showForgetConfirm = true },
                onColorPickRequested = {},
            )
        }
    }

    if (showGamePicker) {
        GamePickerDialog(
            title = "Verknuepfen: ${shortUid(tag.uid)}",
            games = pickableGames,
            onPick = { game ->
                vm.action("/api/link_tag", jsonOf("uid" to tag.uid, "game_uid" to game.uid)) { onDismiss() }
                showGamePicker = false
            },
            onDismiss = { showGamePicker = false },
        )
    }

    if (showForgetConfirm) {
        AlertDialog(
            onDismissRequest = { showForgetConfirm = false },
            title = { Text("Tag loeschen") },
            text = {
                Text(
                    "Versetzt den Pico in den Loeschmodus. Danach den zu loeschenden Tag an den " +
                        "RC522 halten - er wird beim naechsten Erkennen komplett entfernt.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showForgetConfirm = false
                    vm.action("/api/forget_tag", onDone = { onDismiss() })
                }) { Text("Loeschmodus aktivieren") }
            },
            dismissButton = {
                TextButton(onClick = { showForgetConfirm = false }) { Text("Abbrechen") }
            },
        )
    }
}
