package com.bollisoft.steamospico.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ListItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.heightIn
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.data.GameInfo

/** Spiegelt openGamePicker() in dashboard.html: Auswahl eines Spiels fuer die Verknuepfung
 * mit einem Tag, bereits anderweitig verknuepfte Spiele werden vom Aufrufer vorgefiltert. */
@Composable
fun GamePickerDialog(
    title: String,
    games: List<GameInfo>,
    onPick: (GameInfo) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            if (games.isEmpty()) {
                Text("Keine verfuegbaren Spiele (alle bereits verknuepft).")
            } else {
                LazyColumn(modifier = Modifier.heightIn(max = 320.dp)) {
                    items(games) { game ->
                        ListItem(
                            leadingContent = { ColorSwatch(game.color) },
                            headlineContent = { Text(game.name) },
                            modifier = Modifier.clickable { onPick(game) },
                        )
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Abbrechen") }
        },
    )
}
