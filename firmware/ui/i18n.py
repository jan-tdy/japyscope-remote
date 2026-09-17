"""Minimal UI localization for the hand controller.

v0 covers the highest-visibility screens (Home, Menu, boot park check,
park/unpark, about) plus shared footers. Anything not in ``STRINGS`` falls
back to the key itself, and any language missing a translation falls back
to English — so new screens can adopt this incrementally without every
string needing every language up front.
"""
from __future__ import annotations

LANGUAGES: tuple[tuple[str, str], ...] = (
    ("English", "en"),
    ("Slovenčina", "sk"),
)

DEFAULT_LANGUAGE = "en"

STRINGS: dict[str, dict[str, str]] = {
    "home.menu": {"en": "Menu", "sk": "Menu"},
    "home.catalog": {"en": "Catalog", "sk": "Katalóg"},
    "home.dev_tools": {"en": "Dev Tools", "sk": "Vývojárske nástroje"},
    "home.aligned": {"en": "aligned", "sk": "zarovnané"},
    "home.not_aligned": {"en": "Not aligned", "sk": "Nezarovnané"},
    "menu.title": {"en": "MENU", "sk": "MENU"},
    "menu.time_sync": {"en": "Time Sync", "sk": "Synchronizácia času"},
    "menu.alignment": {"en": "Alignment", "sk": "Zarovnanie"},
    "menu.park_toggle": {"en": "Park / Unpark", "sk": "Zaparkovať / Odparkovať"},
    "menu.wifi_access": {"en": "Wi-Fi / Web Access", "sk": "Wi-Fi / Webový prístup"},
    "menu.location": {"en": "Location", "sk": "Poloha"},
    "menu.backlight": {"en": "Backlight", "sk": "Podsvietenie"},
    "menu.language": {"en": "Language", "sk": "Jazyk"},
    "menu.sudo_password": {"en": "Sudo Password", "sk": "Heslo sudo"},
    "menu.system": {"en": "System", "sk": "Systém"},
    "menu.about": {"en": "About", "sk": "O aplikácii"},
    "language.title": {"en": "Language", "sk": "Jazyk"},
    "boot.park_question": {"en": "In park position?", "sk": "Je v parkovacej polohe?"},
    "boot.park_yes": {"en": "Yes — parked", "sk": "Áno — zaparkovaný"},
    "boot.park_no": {"en": "No — sync now", "sk": "Nie — synchronizovať"},
    "boot.sync_failed_1": {"en": "INDI Sync failed", "sk": "INDI synchronizácia zlyhala"},
    "boot.sync_failed_2": {"en": "Position not trusted", "sk": "Poloha nie je overená"},
    "boot.sync_failed_3": {"en": "push=retry", "sk": "push=skúsiť znova"},
    "boot.sync_failed_4": {"en": "9=park question", "sk": "9=otázka parkovania"},
    "park.confirm_question": {"en": "Park the mount?", "sk": "Zaparkovať montáž?"},
    "park.confirm_yes": {"en": "Yes, park", "sk": "Áno, zaparkovať"},
    "park.confirm_cancel": {"en": "Cancel", "sk": "Zrušiť"},
    "park.parking": {"en": "PARKING…", "sk": "PARKOVANIE…"},
    "park.parked_title": {"en": "PARKED", "sk": "ZAPARKOVANÉ"},
    "park.unpark": {"en": "Unpark", "sk": "Odparkovať"},
    "park.power_off": {"en": "Power off", "sk": "Vypnúť"},
    "about.line1": {"en": "JapyScope Remote", "sk": "JapyScope Remote"},
    "about.line2": {"en": "by JapySoft", "sk": "od JapySoft"},
    "about.line3": {"en": "Firmware v0", "sk": "Firmvér v0"},
    "footer.rotate_push": {"en": "rotate · push", "sk": "otočiť · stlačiť"},
    "footer.push_back": {"en": "push/9=back", "sk": "stlačiť/9=späť"},
}


def t(key: str, lang: str, **kwargs: object) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    return text.format(**kwargs) if kwargs else text
