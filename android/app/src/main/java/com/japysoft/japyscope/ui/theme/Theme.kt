package com.japysoft.japyscope.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

// Brand color, matches webui/static/manifest.json theme_color (#0969da).
val BrandPrimary = Color(0xFF0969DA)
val BrandPrimaryDark = Color(0xFF55A6F7)
val BrandBackgroundLight = Color(0xFFF6F8FA)
val BrandBackgroundDark = Color(0xFF0D1117)

private val LightColors = lightColorScheme(
    primary = BrandPrimary,
    onPrimary = Color.White,
    background = BrandBackgroundLight,
    surface = Color.White,
)

private val DarkColors = darkColorScheme(
    primary = BrandPrimaryDark,
    onPrimary = Color.Black,
    background = BrandBackgroundDark,
    surface = Color(0xFF161B22),
)

@Composable
fun JapyScopeTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.primary.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars =
                !darkTheme && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        content = content,
    )
}
