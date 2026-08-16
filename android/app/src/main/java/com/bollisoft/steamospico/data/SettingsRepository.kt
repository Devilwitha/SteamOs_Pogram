package com.bollisoft.steamospico.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "connection_settings")

private object Keys {
    val PC_IP = stringPreferencesKey("pc_ip")
    val PC_PORT = intPreferencesKey("pc_port")
    val TOKEN = stringPreferencesKey("token")
}

/** Persistiert dieselben drei Angaben, die auch Pico/control.html lokal speichert
 * (PC-IP, Port, Token) - Standardport 8090 wie DEFAULT_PORT in gui_server.py. */
class SettingsRepository(private val context: Context) {

    val settingsFlow: Flow<ConnectionSettings> = context.dataStore.data.map { prefs ->
        ConnectionSettings(
            ip = prefs[Keys.PC_IP] ?: "",
            port = prefs[Keys.PC_PORT] ?: 8090,
            token = prefs[Keys.TOKEN] ?: "",
        )
    }

    suspend fun save(ip: String, port: Int, token: String) {
        context.dataStore.edit { prefs ->
            prefs[Keys.PC_IP] = ip.trim()
            prefs[Keys.PC_PORT] = port
            prefs[Keys.TOKEN] = token.trim()
        }
    }
}
