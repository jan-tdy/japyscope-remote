# Third-party notices

JapyScope Remote (the Android app under `android/`) is MIT-licensed, matching the
parent JapyScope Remote project. It depends on the following third-party libraries,
all under the Apache License, Version 2.0:

| Dependency | Version | License |
| --- | --- | --- |
| androidx.core:core-ktx | 1.13.1 | Apache License 2.0 |
| androidx.core:core-splashscreen | 1.0.1 | Apache License 2.0 |
| androidx.lifecycle:lifecycle-runtime-ktx | 2.8.6 | Apache License 2.0 |
| androidx.activity:activity-compose | 1.9.2 | Apache License 2.0 |
| androidx.datastore:datastore-preferences | 1.1.1 | Apache License 2.0 |
| androidx.compose:compose-bom | 2024.09.03 | Apache License 2.0 |
| androidx.compose.ui:ui | (via compose-bom 2024.09.03) | Apache License 2.0 |
| androidx.compose.ui:ui-graphics | (via compose-bom 2024.09.03) | Apache License 2.0 |
| androidx.compose.ui:ui-tooling-preview | (via compose-bom 2024.09.03) | Apache License 2.0 |
| androidx.compose.material3:material3 | (via compose-bom 2024.09.03) | Apache License 2.0 |
| androidx.compose.material:material-icons-extended | (via compose-bom 2024.09.03) | Apache License 2.0 |
| org.jetbrains.kotlinx:kotlinx-coroutines-android | 1.8.1 | Apache License 2.0 |

Device discovery uses `android.net.nsd.NsdManager`, part of the Android platform SDK
(no separate dependency, so no separate license entry).

Full license text: <https://www.apache.org/licenses/LICENSE-2.0>.
