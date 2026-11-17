package com.japysoft.japyscope.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

private const val TAG = "NsdDeviceDiscovery"

/** The DNS-SD service type the Pi advertises over mDNS (see install/avahi-japyscope.service). */
const val JAPYSCOPE_SERVICE_TYPE = "_japyscope._tcp."

/** A JapyScope device found on the local network, with its service name resolved to host:port. */
data class JapyDevice(
    val name: String,
    val host: String,
    val port: Int,
)

/**
 * Browses for `_japyscope._tcp.` services with [NsdManager] and resolves each one found.
 *
 * Holds a Wi-Fi multicast lock for the lifetime of a scan: mDNS announcements and queries are
 * multicast packets, which Android drops for apps unless a multicast lock is held.
 *
 * Resolve requests are serialized because NsdManager only supports one outstanding
 * resolveService() call at a time; concurrent calls fail with FAILURE_ALREADY_ACTIVE.
 */
class NsdDeviceDiscovery(context: Context) {

    private val nsdManager = context.applicationContext
        .getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifiManager = context.applicationContext
        .getSystemService(Context.WIFI_SERVICE) as WifiManager

    private var multicastLock: WifiManager.MulticastLock? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    private val resolveQueue = ArrayDeque<NsdServiceInfo>()
    private var resolveInFlight = false

    private val _devices = MutableStateFlow<List<JapyDevice>>(emptyList())
    val devices: StateFlow<List<JapyDevice>> = _devices.asStateFlow()

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning.asStateFlow()

    fun startDiscovery() {
        if (discoveryListener != null) return

        _devices.value = emptyList()
        resolveQueue.clear()
        resolveInFlight = false

        val lock = wifiManager.createMulticastLock("japyscope-nsd-discovery")
        lock.setReferenceCounted(true)
        lock.acquire()
        multicastLock = lock

        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
                _isScanning.value = true
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (serviceInfo.serviceType.startsWith("_japyscope")) {
                    enqueueResolve(serviceInfo)
                }
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                _devices.value = _devices.value.filterNot { it.name == serviceInfo.serviceName }
            }

            override fun onDiscoveryStopped(serviceType: String) {
                _isScanning.value = false
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "Start discovery failed: $errorCode")
                _isScanning.value = false
                discoveryListener = null
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "Stop discovery failed: $errorCode")
                _isScanning.value = false
            }
        }
        discoveryListener = listener
        nsdManager.discoverServices(JAPYSCOPE_SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
    }

    fun stopDiscovery() {
        discoveryListener?.let {
            try {
                nsdManager.stopServiceDiscovery(it)
            } catch (e: IllegalArgumentException) {
                // Listener was already unregistered (e.g. onStartDiscoveryFailed already ran).
                Log.w(TAG, "stopServiceDiscovery: listener not registered", e)
            }
        }
        discoveryListener = null
        resolveQueue.clear()
        resolveInFlight = false
        _isScanning.value = false

        multicastLock?.let { if (it.isHeld) it.release() }
        multicastLock = null
    }

    private fun enqueueResolve(serviceInfo: NsdServiceInfo) {
        resolveQueue.addLast(serviceInfo)
        resolveNext()
    }

    @Suppress("DEPRECATION")
    private fun resolveNext() {
        if (resolveInFlight) return
        val next = resolveQueue.removeFirstOrNull() ?: return
        resolveInFlight = true

        nsdManager.resolveService(next, object : NsdManager.ResolveListener {
            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "Resolve failed for ${serviceInfo.serviceName}: $errorCode")
                resolveInFlight = false
                resolveNext()
            }

            override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                val host = serviceInfo.host?.hostAddress
                if (host != null) {
                    val device = JapyDevice(
                        name = serviceInfo.serviceName,
                        host = host,
                        port = serviceInfo.port,
                    )
                    _devices.value = (_devices.value.filterNot { it.name == device.name }) + device
                }
                resolveInFlight = false
                resolveNext()
            }
        })
    }
}
