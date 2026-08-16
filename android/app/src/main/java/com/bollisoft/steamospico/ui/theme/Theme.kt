package com.bollisoft.steamospico.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val HudColorScheme = darkColorScheme(
    primary = HudCyan,
    onPrimary = HudBg,
    secondary = HudMagenta,
    onSecondary = HudBg,
    tertiary = HudGreen,
    onTertiary = HudBg,
    background = HudBg,
    onBackground = HudText,
    surface = HudPanel,
    onSurface = HudText,
    surfaceVariant = HudPanel2,
    onSurfaceVariant = HudDim,
    outline = HudBorder,
    error = HudRed,
    onError = HudBg,
)

/** Die Web-GUI ist bewusst dauerhaft dunkel (color-scheme:dark in allen drei HTML-Seiten) -
 * die App spiegelt das 1:1, unabhaengig vom System-Theme des Telefons. */
@Composable
fun SteamOsPicoTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = HudColorScheme,
        content = content,
    )
}
