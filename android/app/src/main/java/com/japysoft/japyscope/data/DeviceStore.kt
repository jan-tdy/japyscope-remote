package com.japysoft.japyscope.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.japysoft.japyscope.discovery.JapyDevice
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.deviceDataStore by preferencesDataStore(name = "japyscope_device")

/** Persists the last connected device so the app can reconnect without a fresh scan. */
class DeviceStore(private val context: Context) {

    private object Keys {
        val HAS_DEVICE = booleanPreferencesKey("has_device")
        val NAME = stringPreferencesKey("device_name")
        val HOST = stringPreferencesKey("device_host")
        val PORT = intPreferencesKey("device_port")
    }

    val savedDevice: Flow<JapyDevice?> = context.deviceDataStore.data.map { prefs ->
        if (prefs[Keys.HAS_DEVICE] != true) return@map null
        val name = prefs[Keys.NAME] ?: return@map null
        val host = prefs[Keys.HOST] ?: return@map null
        val port = prefs[Keys.PORT] ?: return@map null
        JapyDevice(name = name, host = host, port = port)
    }

    suspend fun getSavedDevice(): JapyDevice? = savedDevice.first()

    suspend fun save(device: JapyDevice) {
        context.deviceDataStore.edit { prefs ->
            prefs[Keys.HAS_DEVICE] = true
            prefs[Keys.NAME] = device.name
            prefs[Keys.HOST] = device.host
            prefs[Keys.PORT] = device.port
        }
    }

    suspend fun clear() {
        context.deviceDataStore.edit { prefs ->
            prefs.clear()
        }
    }
}
