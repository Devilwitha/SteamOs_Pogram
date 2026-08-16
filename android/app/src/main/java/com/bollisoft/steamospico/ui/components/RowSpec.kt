package com.bollisoft.steamospico.ui.components

/**
 * Generisches Zeilenmodell, das die Kategorien im Controller-Menue (LEDs/Sound/Spiele/Tags/
 * Werkzeuge/Info) beschreibt - mirrort toggleRow()/colorRow()/enumRow()/buttonRow()/infoRow()/
 * statRow() aus dashboard.html: jede Kategorie liefert eine Liste solcher Zeilen, eine
 * gemeinsame Rendering-Funktion (SettingRow) stellt sie dar.
 */
sealed interface RowSpec {
    val label: String

    data class Toggle(
        override val label: String,
        val value: Boolean,
        val onToggle: () -> Unit,
    ) : RowSpec

    data class ColorPick(
        override val label: String,
        val color: String,
        val onSetColor: (String) -> Unit,
    ) : RowSpec

    data class Enum(
        override val label: String,
        val hint: String,
        val onCycle: () -> Unit,
    ) : RowSpec

    data class Action(
        override val label: String,
        val enabled: Boolean = true,
        val onClick: () -> Unit,
    ) : RowSpec

    data class Info(
        override val label: String,
    ) : RowSpec

    data class Stat(
        override val label: String,
        val value: String,
    ) : RowSpec

    data class ListEntry(
        override val label: String,
        val color: String? = null,
        val badge: String? = null,
        val subtext: String? = null,
        val dimmed: Boolean = false,
        val onClick: () -> Unit,
    ) : RowSpec
}
