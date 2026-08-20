package com.bollisoft.steamospico

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.SportsEsports
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.bollisoft.steamospico.ui.PicoViewModel
import com.bollisoft.steamospico.ui.screens.AdminScreen
import com.bollisoft.steamospico.ui.screens.ConsoleScreen
import com.bollisoft.steamospico.ui.screens.SettingsScreen
import com.bollisoft.steamospico.ui.theme.SteamOsPicoTheme

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SteamOsPicoTheme {
                Surface(color = MaterialTheme.colorScheme.background) {
                    val vm: PicoViewModel = viewModel()
                    AppRoot(vm)
                }
            }
        }
    }
}

private enum class Screen(val label: String) {
    CONSOLE("Konsole"),
    ADMIN("Verwaltung"),
    SETTINGS("Verbindung"),
}

@Composable
private fun AppRoot(vm: PicoViewModel) {
    var screen by remember { mutableStateOf(Screen.CONSOLE) }
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(vm) {
        vm.toast.collect { message ->
            snackbarHostState.showSnackbar(message.text)
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = screen == Screen.CONSOLE,
                    onClick = { screen = Screen.CONSOLE },
                    icon = { Icon(Icons.Filled.SportsEsports, contentDescription = null) },
                    label = { Text(Screen.CONSOLE.label) },
                )
                NavigationBarItem(
                    selected = screen == Screen.ADMIN,
                    onClick = { screen = Screen.ADMIN },
                    icon = { Icon(Icons.Filled.Build, contentDescription = null) },
                    label = { Text(Screen.ADMIN.label) },
                )
                NavigationBarItem(
                    selected = screen == Screen.SETTINGS,
                    onClick = { screen = Screen.SETTINGS },
                    icon = { Icon(Icons.Filled.Wifi, contentDescription = null) },
                    label = { Text(Screen.SETTINGS.label) },
                )
            }
        },
    ) { padding ->
        when (screen) {
            Screen.CONSOLE -> ConsoleScreen(vm, modifier = Modifier.padding(padding))
            Screen.ADMIN -> AdminScreen(vm, modifier = Modifier.padding(padding))
            Screen.SETTINGS -> SettingsScreen(vm, modifier = Modifier.padding(padding))
        }
    }
}
