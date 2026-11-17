package com.japysoft.japyscope

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.japysoft.japyscope.data.DeviceStore
import com.japysoft.japyscope.data.isDeviceReachable
import com.japysoft.japyscope.discovery.JapyDevice
import com.japysoft.japyscope.discovery.NsdDeviceDiscovery
import com.japysoft.japyscope.ui.DiscoveryScreen
import com.japysoft.japyscope.ui.WebViewScreen
import com.japysoft.japyscope.ui.theme.JapyScopeTheme
import kotlinx.coroutines.launch

private sealed interface AppScreen {
    data object CheckingSavedDevice : AppScreen
    data class Discovery(val unreachableDeviceName: String?) : AppScreen
    data class Connected(val device: JapyDevice) : AppScreen
}

class MainActivity : ComponentActivity() {

    private lateinit var deviceStore: DeviceStore
    private lateinit var discovery: NsdDeviceDiscovery

    override fun onCreate(savedInstanceState: Bundle?) {
        val splashScreen = installSplashScreen()
        super.onCreate(savedInstanceState)

        deviceStore = DeviceStore(this)
        discovery = NsdDeviceDiscovery(this)

        var keepSplash = true
        splashScreen.setKeepOnScreenCondition { keepSplash }

        setContent {
            JapyScopeTheme {
                var screen by remember { mutableStateOf<AppScreen>(AppScreen.CheckingSavedDevice) }
                val scope = rememberCoroutineScope()

                LaunchedEffect(Unit) {
                    val saved = deviceStore.getSavedDevice()
                    screen = if (saved == null) {
                        AppScreen.Discovery(unreachableDeviceName = null)
                    } else if (isDeviceReachable(saved.host, saved.port)) {
                        AppScreen.Connected(saved)
                    } else {
                        AppScreen.Discovery(unreachableDeviceName = saved.name)
                    }
                    keepSplash = false
                }

                when (val current = screen) {
                    is AppScreen.CheckingSavedDevice -> {
                        // Splash screen is still showing; render nothing underneath it.
                    }

                    is AppScreen.Discovery -> DiscoveryScreen(
                        discovery = discovery,
                        unreachableDeviceName = current.unreachableDeviceName,
                        onForgetDevice = {
                            scope.launch {
                                deviceStore.clear()
                                screen = AppScreen.Discovery(unreachableDeviceName = null)
                            }
                        },
                        onDeviceSelected = { device ->
                            scope.launch {
                                deviceStore.save(device)
                                screen = AppScreen.Connected(device)
                            }
                        },
                    )

                    is AppScreen.Connected -> WebViewScreen(
                        device = current.device,
                        onSwitchDevice = {
                            scope.launch {
                                deviceStore.clear()
                                screen = AppScreen.Discovery(unreachableDeviceName = null)
                            }
                        },
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        discovery.stopDiscovery()
        super.onDestroy()
    }
}
