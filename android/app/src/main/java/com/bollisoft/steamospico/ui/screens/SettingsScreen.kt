package com.bollisoft.steamospico.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.bollisoft.steamospico.ui.PicoViewModel
import kotlinx.coroutines.launch

/**
 * Entspricht der "Verbindung zum PC"-Karte in Pico/control.html: IP/Port/Token von
 * steamOs/gui/gui_server.py, lokal auf dem Geraet gespeichert (dort im Pico-Dateisystem).
 */
@Composable
fun SettingsScreen(vm: PicoViewModel, modifier: Modifier = Modifier) {
    val settings by vm.settings.collectAsState()
    val state by vm.state.collectAsState()
    val connectionError by vm.connectionError.collectAsState()
    val loading by vm.loading.collectAsState()
    val scope = rememberCoroutineScope()

    var ip by remember(settings.ip) { mutableStateOf(settings.ip) }
    var portText by remember(settings.port) { mutableStateOf(settings.port.toString()) }
    var token by remember(settings.token) { mutableStateOf(settings.token) }
    var tokenVisible by remember { mutableStateOf(false) }
    var initialized by remember { mutableStateOf(false) }

    LaunchedEffect(settings) {
        if (!initialized) {
            ip = settings.ip
            portText = settings.port.toString()
            token = settings.token
            initialized = true
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
    ) {
        Text(
            "Verbindung zum PC",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "IP und Port von steamOs/gui/gui_server.py auf dem PC (Standardport 8090), sowie " +
                "das dort in config.json unter \"remote_control_token\" hinterlegte Token. Ohne " +
                "passendes Token lehnt der PC alle Anfragen von hier ab.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(bottom = 20.dp),
        )

        OutlinedTextField(
            value = ip,
            onValueChange = { ip = it },
            label = { Text("PC-IP") },
            placeholder = { Text("z.B. 192.168.178.50") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = portText,
            onValueChange = { v -> if (v.length <= 5 && v.all { it.isDigit() }) portText = v },
            label = { Text("Port") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = token,
            onValueChange = { token = it },
            label = { Text("Token") },
            placeholder = { Text("siehe config.json: remote_control_token") },
            singleLine = true,
            visualTransformation = if (tokenVisible) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { tokenVisible = !tokenVisible }) {
                    Icon(
                        if (tokenVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                        contentDescription = if (tokenVisible) "Verbergen" else "Anzeigen",
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Button(onClick = {
                val port = portText.toIntOrNull() ?: 8090
                vm.saveSettings(ip.trim(), port, token.trim())
            }) { Text("Speichern") }

            OutlinedButton(onClick = { scope.launch { vm.refresh() } }) {
                Text("Verbindung testen")
            }
        }

        Card(modifier = Modifier.fillMaxWidth().padding(top = 20.dp)) {
            Column(Modifier.padding(16.dp)) {
                when {
                    loading -> Row {
                        CircularProgressIndicator(modifier = Modifier.padding(end = 12.dp))
                        Text("Verbinde...")
                    }

                    state != null -> Row {
                        Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.tertiary)
                        Column(Modifier.padding(start = 12.dp)) {
                            Text("Verbunden - ${state!!.games.size} Spiel(e) gefunden.")
                            Text(
                                "Pico erreichbar: " + if (state!!.picoReachable) "Ja" else "Nein",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }

                    connectionError != null -> Row {
                        Icon(Icons.Filled.Error, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                        Text(connectionError ?: "Fehler", modifier = Modifier.padding(start = 12.dp))
                    }

                    else -> Text("Noch keine Verbindung getestet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
