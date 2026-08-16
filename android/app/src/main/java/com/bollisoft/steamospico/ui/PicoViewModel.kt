package com.bollisoft.steamospico.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.bollisoft.steamospico.data.AppState
import com.bollisoft.steamospico.data.ConnectionSettings
import com.bollisoft.steamospico.data.PicoApiClient
import com.bollisoft.steamospico.data.SettingsRepository
import com.bollisoft.steamospico.data.parseAppState
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

data class ToastMessage(val text: String, val ok: Boolean)

/**
 * Haelt denselben Zustand wie `state` in dashboard.html: pollt alle 5s /api/state (siehe
 * loadState()/setInterval dort) und schickt Aktionen an dieselben /api/...-Routen. Eine einzige
 * Instanz wird von allen drei Screens (Konsole/Verwaltung/Verbindung) geteilt.
 */
class PicoViewModel(application: Application) : AndroidViewModel(application) {

    private val settingsRepo = SettingsRepository(application)

    private val _settings = MutableStateFlow(ConnectionSettings("", 8090, ""))
    val settings: StateFlow<ConnectionSettings> = _settings.asStateFlow()

    private val api = PicoApiClient { _settings.value }

    private val _state = MutableStateFlow<AppState?>(null)
    val state: StateFlow<AppState?> = _state.asStateFlow()

    private val _connectionError = MutableStateFlow<String?>(null)
    val connectionError: StateFlow<String?> = _connectionError.asStateFlow()

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _toast = MutableSharedFlow<ToastMessage>(extraBufferCapacity = 8)
    val toast: SharedFlow<ToastMessage> = _toast.asSharedFlow()

    init {
        viewModelScope.launch {
            settingsRepo.settingsFlow.collect { s ->
                val wasConfigured = _settings.value.isConfigured
                _settings.value = s
                if (!wasConfigured && s.isConfigured) refresh()
            }
        }
        viewModelScope.launch {
            while (isActive) {
                refresh()
                kotlinx.coroutines.delay(5000)
            }
        }
    }

    fun saveSettings(ip: String, port: Int, token: String) {
        viewModelScope.launch { settingsRepo.save(ip, port, token) }
    }

    suspend fun refresh() {
        if (!_settings.value.isConfigured) return
        _loading.value = true
        api.getState()
            .onSuccess { json ->
                _state.value = parseAppState(json)
                _connectionError.value = null
            }
            .onFailure { e -> _connectionError.value = e.message }
        _loading.value = false
    }

    fun refreshNow() {
        viewModelScope.launch { refresh() }
    }

    /** Fuehrt eine JSON-Aktion aus, zeigt die Server-Antwort als Toast und laedt den Zustand
     * neu - genau wie afterAction()/toast()+loadState() in dashboard.html. */
    fun action(path: String, body: JSONObject = JSONObject(), onDone: ((Boolean) -> Unit)? = null) {
        viewModelScope.launch {
            val result = api.post(path, body)
            _toast.emit(ToastMessage(result.message, result.ok))
            refresh()
            onDone?.invoke(result.ok)
        }
    }

    fun uploadFile(
        path: String,
        fileField: String,
        fileName: String,
        bytes: ByteArray,
        mimeType: String,
        extraFields: Map<String, String> = emptyMap(),
    ) {
        viewModelScope.launch {
            val result = api.postMultipart(path, fileField, fileName, bytes, mimeType, extraFields)
            _toast.emit(ToastMessage(result.message, result.ok))
            refresh()
        }
    }
}

fun jsonOf(vararg pairs: Pair<String, Any?>): JSONObject {
    val obj = JSONObject()
    for ((k, v) in pairs) obj.put(k, v)
    return obj
}
