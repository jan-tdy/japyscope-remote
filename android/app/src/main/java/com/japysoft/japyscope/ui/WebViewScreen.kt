package com.japysoft.japyscope.ui

import android.annotation.SuppressLint
import android.content.Intent
import android.view.ViewGroup
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.japysoft.japyscope.R
import com.japysoft.japyscope.discovery.JapyDevice

/** Literal suffix the Pi's webui matches on (see webui/app.py context processor). */
const val WEBVIEW_USER_AGENT_SUFFIX = "JapyScopeApp/1.0"

private sealed interface LoadState {
    data object Loading : LoadState
    data object Loaded : LoadState
    data class Error(val reason: String) : LoadState
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WebViewScreen(
    device: JapyDevice,
    onSwitchDevice: () -> Unit,
) {
    var webView by remember { mutableStateOf<WebView?>(null) }
    var loadState by remember(device) { mutableStateOf<LoadState>(LoadState.Loading) }

    val baseUrl = "http://${device.host}:${device.port}/"

    BackHandler(enabled = true) {
        val wv = webView
        if (wv != null && wv.canGoBack()) {
            wv.goBack()
        } else {
            onSwitchDevice()
        }
    }

    DisposableEffect(device) {
        onDispose {
            webView?.apply {
                stopLoading()
                destroy()
            }
            webView = null
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(device.name) },
                navigationIcon = {
                    IconButton(onClick = {
                        webView?.evaluateJavascript(
                            "document.querySelector('.nav-toggle')?.click();",
                            null,
                        )
                    }) {
                        Icon(Icons.Default.Menu, contentDescription = stringResource(R.string.webui_menu_action))
                    }
                },
                actions = {
                    IconButton(onClick = onSwitchDevice) {
                        Icon(
                            Icons.Default.SwapHoriz,
                            contentDescription = stringResource(R.string.webui_switch_device_action),
                        )
                    }
                },
            )
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            JapyWebView(
                baseUrl = baseUrl,
                expectedHost = device.host,
                onWebViewReady = { webView = it },
                onLoadStarted = { loadState = LoadState.Loading },
                onLoadFinished = { loadState = LoadState.Loaded },
                onLoadError = { reason -> loadState = LoadState.Error(reason) },
            )

            when (val state = loadState) {
                is LoadState.Loading -> LoadingOverlay()
                is LoadState.Error -> ConnectionLostOverlay(
                    deviceName = device.name,
                    reason = state.reason,
                    onRetry = { webView?.reload() },
                    onSwitchDevice = onSwitchDevice,
                )
                is LoadState.Loaded -> Unit
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun JapyWebView(
    baseUrl: String,
    expectedHost: String,
    onWebViewReady: (WebView) -> Unit,
    onLoadStarted: () -> Unit,
    onLoadFinished: () -> Unit,
    onLoadError: (String) -> Unit,
) {
    val context = LocalContext.current

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = {
            WebView(context).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.userAgentString = "${settings.userAgentString} $WEBVIEW_USER_AGENT_SUFFIX"

                webViewClient = object : WebViewClient() {
                    // onPageFinished still fires after a failed main-frame load, so track
                    // whether this navigation already reported an error and ignore the
                    // "finished" callback for it instead of flipping back to Loaded.
                    var currentLoadFailed = false

                    override fun shouldOverrideUrlLoading(
                        view: WebView,
                        request: WebResourceRequest,
                    ): Boolean {
                        val url = request.url
                        if (url.host == expectedHost) {
                            return false
                        }
                        val intent = Intent(Intent.ACTION_VIEW, url)
                        return try {
                            context.startActivity(intent)
                            true
                        } catch (e: Exception) {
                            false
                        }
                    }

                    override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) {
                        currentLoadFailed = false
                        onLoadStarted()
                    }

                    override fun onPageFinished(view: WebView, url: String?) {
                        if (!currentLoadFailed) {
                            onLoadFinished()
                        }
                    }

                    override fun onReceivedError(
                        view: WebView,
                        request: WebResourceRequest,
                        error: WebResourceError,
                    ) {
                        if (request.isForMainFrame) {
                            currentLoadFailed = true
                            onLoadError(error.description?.toString() ?: "Connection error")
                        }
                    }
                }

                loadUrl(baseUrl)
                onWebViewReady(this)
            }
        },
    )
}

@Composable
private fun LoadingOverlay() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun ConnectionLostOverlay(
    deviceName: String,
    reason: String,
    onRetry: () -> Unit,
    onSwitchDevice: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier.padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(
                Icons.Default.CloudOff,
                contentDescription = null,
                modifier = Modifier.size(56.dp),
                tint = MaterialTheme.colorScheme.error,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.webui_connection_lost_title),
                style = MaterialTheme.typography.titleLarge,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = stringResource(R.string.webui_connection_lost_reason, deviceName, reason),
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(24.dp))
            Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.webui_retry))
            }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = onSwitchDevice, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.webui_switch_device))
            }
        }
    }
}
