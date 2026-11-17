package com.japysoft.japyscope.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/**
 * Hits the webui's unauthenticated `GET /healthz` endpoint to check a device is reachable.
 * Used both to auto-reconnect to a remembered device and to validate a manually-entered address.
 */
suspend fun isDeviceReachable(host: String, port: Int, timeoutMs: Int = 2500): Boolean =
    withContext(Dispatchers.IO) {
        var connection: HttpURLConnection? = null
        try {
            val url = URL("http://$host:$port/healthz")
            connection = (url.openConnection() as HttpURLConnection).apply {
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                requestMethod = "GET"
            }
            connection.responseCode == 200
        } catch (e: Exception) {
            false
        } finally {
            connection?.disconnect()
        }
    }
