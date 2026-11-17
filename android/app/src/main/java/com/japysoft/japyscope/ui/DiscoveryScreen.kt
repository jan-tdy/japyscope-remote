package com.japysoft.japyscope.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.japysoft.japyscope.R
import com.japysoft.japyscope.data.isDeviceReachable
import com.japysoft.japyscope.discovery.JapyDevice
import com.japysoft.japyscope.discovery.NsdDeviceDiscovery
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoveryScreen(
    discovery: NsdDeviceDiscovery,
    unreachableDeviceName: String?,
    onForgetDevice: () -> Unit,
    onDeviceSelected: (JapyDevice) -> Unit,
) {
    val devices by discovery.devices.collectAsState()
    val isScanning by discovery.isScanning.collectAsState()

    DisposableEffect(Unit) {
        discovery.startDiscovery()
        onDispose { discovery.stopDiscovery() }
    }

    var manualEntryExpanded by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text(stringResource(R.string.discovery_title)) })
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            if (unreachableDeviceName != null) {
                UnreachableBanner(
                    deviceName = unreachableDeviceName,
                    onForget = onForgetDevice,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(16.dp, 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = if (isScanning) {
                        stringResource(R.string.discovery_searching)
                    } else {
                        stringResource(R.string.discovery_title)
                    },
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = {
                    discovery.stopDiscovery()
                    discovery.startDiscovery()
                }) {
                    Icon(Icons.Default.Refresh, contentDescription = null)
                    Spacer(Modifier.size(4.dp))
                    Text(stringResource(R.string.discovery_scan_again))
                }
            }

            Box(modifier = Modifier.weight(1f, fill = true)) {
                when {
                    devices.isEmpty() && isScanning -> LoadingState()
                    devices.isEmpty() -> EmptyState()
                    else -> LazyColumn {
                        items(devices, key = { it.name }) { device ->
                            DeviceRow(device = device, onClick = { onDeviceSelected(device) })
                        }
                    }
                }
            }

            ManualEntrySection(
                expanded = manualEntryExpanded,
                onToggle = { manualEntryExpanded = !manualEntryExpanded },
                onConnect = onDeviceSelected,
            )
        }
    }
}

@Composable
private fun UnreachableBanner(deviceName: String, onForget: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
        ),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onErrorContainer,
                )
                Spacer(Modifier.size(8.dp))
                Text(
                    text = stringResource(R.string.discovery_unreachable_banner, deviceName),
                    color = MaterialTheme.colorScheme.onErrorContainer,
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(4.dp))
            TextButton(onClick = onForget) {
                Text(stringResource(R.string.discovery_forget_device))
            }
        }
    }
}

@Composable
private fun LoadingState() {
    Column(
        modifier = Modifier.fillMaxWidth().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.height(16.dp))
        Text(
            text = stringResource(R.string.discovery_searching),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun EmptyState() {
    Column(
        modifier = Modifier.fillMaxWidth().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            Icons.Default.Wifi,
            contentDescription = null,
            modifier = Modifier.size(48.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(16.dp))
        Text(
            text = stringResource(R.string.discovery_empty),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun DeviceRow(device: JapyDevice, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(device.name) },
        supportingContent = {
            Text(stringResource(R.string.discovery_device_subtitle, device.host, device.port))
        },
        leadingContent = { Icon(Icons.Default.Wifi, contentDescription = null) },
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    )
}

@Composable
private fun ManualEntrySection(
    expanded: Boolean,
    onToggle: () -> Unit,
    onConnect: (JapyDevice) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("8080") }
    var checking by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        TextButton(onClick = onToggle) {
            Text(stringResource(R.string.discovery_manual_toggle))
        }
        if (expanded) {
            OutlinedTextField(
                value = host,
                onValueChange = { host = it; error = null },
                label = { Text(stringResource(R.string.discovery_manual_host_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = port,
                onValueChange = { port = it.filter(Char::isDigit); error = null },
                label = { Text(stringResource(R.string.discovery_manual_port_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            if (error != null) {
                Text(error!!, color = MaterialTheme.colorScheme.error)
                Spacer(Modifier.height(8.dp))
            }
            Button(
                enabled = host.isNotBlank() && port.isNotBlank() && !checking,
                onClick = {
                    val portNum = port.toIntOrNull()
                    if (portNum == null) {
                        error = "Enter a valid port"
                        return@Button
                    }
                    checking = true
                    error = null
                    scope.launch {
                        val reachable = isDeviceReachable(host, portNum)
                        checking = false
                        if (reachable) {
                            onConnect(JapyDevice(name = host, host = host, port = portNum))
                        } else {
                            error = "Couldn't reach $host:$portNum"
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (checking) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp))
                } else {
                    Text(stringResource(R.string.discovery_manual_connect))
                }
            }
        }
    }
}
