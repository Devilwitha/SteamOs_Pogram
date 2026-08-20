package com.bollisoft.steamospico.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.data.COLOR_PALETTE

/** Spiegelt PALETTE + colorRow().onCycle in dashboard.html: feste Palette per Antippen statt
 * eines echten Farbwaehlers, zusaetzlich ein freies Hex-Feld fuer individuelle Farben (wie
 * ueber /admin per <input type=color> moeglich). */
@Composable
fun ColorPickerDialog(
    title: String,
    currentColor: String,
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var hexInput by remember(currentColor) { mutableStateOf(currentColor.removePrefix("#").uppercase()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(6),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(112.dp),
                ) {
                    items(COLOR_PALETTE) { hex ->
                        Row(
                            modifier = Modifier
                                .padding(4.dp)
                                .aspectRatio(1f)
                                .clip(RoundedCornerShape(8.dp))
                                .background(colorFromHex(hex))
                                .border(
                                    width = if (hex.equals(currentColor, ignoreCase = true)) 2.dp else 1.dp,
                                    color = if (hex.equals(currentColor, ignoreCase = true)) {
                                        MaterialTheme.colorScheme.primary
                                    } else {
                                        Color.White.copy(alpha = 0.3f)
                                    },
                                    shape = RoundedCornerShape(8.dp),
                                )
                                .clickable { onPick(hex) },
                        ) {}
                    }
                }
                OutlinedTextField(
                    value = hexInput,
                    onValueChange = { hexInput = it.filter { c -> c.isLetterOrDigit() }.take(6).uppercase() },
                    label = { Text("Eigener Hex-Wert") },
                    prefix = { Text("#") },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 12.dp),
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = hexInput.length == 6,
                onClick = { onPick("#$hexInput") },
            ) { Text("Uebernehmen") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Abbrechen") }
        },
    )
}
