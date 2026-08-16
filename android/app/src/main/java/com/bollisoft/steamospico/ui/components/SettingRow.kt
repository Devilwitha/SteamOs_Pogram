package com.bollisoft.steamospico.ui.components

import android.graphics.Color as AndroidColor
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

fun colorFromHex(hex: String?, fallback: Color = HudDimColor): Color = try {
    if (hex.isNullOrBlank()) fallback else Color(AndroidColor.parseColor(hex))
} catch (e: IllegalArgumentException) {
    fallback
}

val HudDimColor = Color(0xFF7686A0)

@Composable
fun ColorSwatch(hex: String?, size: androidx.compose.ui.unit.Dp = 20.dp) {
    Row(
        modifier = Modifier
            .size(size)
            .clip(RoundedCornerShape(4.dp))
            .background(colorFromHex(hex))
            .border(1.dp, Color.White.copy(alpha = 0.25f), RoundedCornerShape(4.dp))
    ) {}
}

@Composable
fun SettingRow(row: RowSpec, onColorPickRequested: (RowSpec.ColorPick) -> Unit) {
    when (row) {
        is RowSpec.Info -> {
            Text(
                text = row.label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            )
        }

        is RowSpec.Stat -> {
            ListItem(
                headlineContent = { Text(row.label) },
                trailingContent = {
                    Text(row.value, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodyMedium)
                },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
            )
        }

        is RowSpec.Toggle -> {
            ListItem(
                headlineContent = { Text(row.label) },
                trailingContent = { Switch(checked = row.value, onCheckedChange = { row.onToggle() }) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                modifier = Modifier.clickable { row.onToggle() },
            )
        }

        is RowSpec.ColorPick -> {
            ListItem(
                headlineContent = { Text(row.label) },
                trailingContent = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        ColorSwatch(row.color)
                        Text(
                            row.color.uppercase(),
                            modifier = Modifier.padding(start = 8.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                modifier = Modifier.clickable { onColorPickRequested(row) },
            )
        }

        is RowSpec.Enum -> {
            ListItem(
                headlineContent = { Text(row.label) },
                trailingContent = {
                    Text(row.hint, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodyMedium)
                },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                modifier = Modifier.clickable { row.onCycle() },
            )
        }

        is RowSpec.Action -> {
            ListItem(
                headlineContent = { Text(row.label, color = if (row.enabled) Color.Unspecified else MaterialTheme.colorScheme.onSurfaceVariant) },
                trailingContent = { Icon(Icons.Filled.ChevronRight, contentDescription = null) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                modifier = Modifier
                    .alpha(if (row.enabled) 1f else 0.5f)
                    .clickable(enabled = row.enabled) { row.onClick() },
            )
        }

        is RowSpec.ListEntry -> {
            ListItem(
                leadingContent = row.color?.let { c -> { ColorSwatch(c) } },
                headlineContent = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(row.label)
                        if (row.badge != null) {
                            Text(
                                row.badge.uppercase(),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.tertiary,
                                modifier = Modifier
                                    .padding(start = 8.dp)
                                    .border(1.dp, MaterialTheme.colorScheme.tertiary.copy(alpha = 0.4f), RoundedCornerShape(4.dp))
                                    .padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                },
                supportingContent = row.subtext?.let { s -> { Text(s) } },
                trailingContent = { Icon(Icons.Filled.ChevronRight, contentDescription = null) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                modifier = Modifier
                    .alpha(if (row.dimmed) 0.55f else 1f)
                    .clickable { row.onClick() },
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
}
