"""Server-rendered JapyScope administration UI."""
from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import logging
import os
import secrets
import sqlite3
import subprocess
import threading
import time
from functools import wraps
from typing import Callable, Optional

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from shared.db import AccessCodeRepo, CatalogRepo, HARDWARE_COMPONENTS, SettingsRepo, StateRepo, db_session

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 1_000_000
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 30


def _default_wifi_configurator(ssid: str, password: str) -> None:
    subprocess.run(
        ["sudo", "/usr/local/sbin/japyscope-wifi", ssid],
        input=(password + "\n").encode("utf-8"), check=True, timeout=30,
    )


def _default_action_runner(command: list[str]) -> None:
    subprocess.Popen(command, start_new_session=True)


def create_app(
    db_path: Optional[str] = None,
    wifi_configurator: Callable[[str, str], None] = _default_wifi_configurator,
    action_runner: Callable[[list[str]], None] = _default_action_runner,
) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=db_path or os.environ.get("JAPYSCOPE_DB_PATH", "/var/lib/japyscope/japyscope.db"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        SECRET_KEY=os.environ.get("JAPYSCOPE_SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    attempts: dict[str, dict[str, float]] = {}
    attempts_lock = threading.Lock()

    def auth_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("authenticated"):
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def verify_csrf():
        if request.method != "POST" or request.endpoint == "login":
            return None
        supplied = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not supplied or not expected or not secrets.compare_digest(supplied, expected):
            abort(400, "Invalid CSRF token")
        return None

    @app.context_processor
    def common_template_values():
        token = session.setdefault("csrf_token", secrets.token_urlsafe(24))
        return {"csrf_token": token}

    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html")
        address = request.remote_addr or "unknown"
        now = time.monotonic()
        with attempts_lock:
            record = attempts.setdefault(address, {"count": 0, "until": 0})
            if record["until"] > now:
                flash(f"Locked out. Try again in {int(record['until'] - now) + 1}s.", "error")
                return render_template("login.html"), 429
        code = request.form.get("code", "").strip()
        with db_session(app.config["DATABASE"]) as conn:
            valid = bool(code) and AccessCodeRepo(conn).is_valid(code)
        with attempts_lock:
            record = attempts[address]
            if not valid:
                record["count"] += 1
                if record["count"] >= MAX_LOGIN_ATTEMPTS:
                    record.update(count=0, until=now + LOCKOUT_SECONDS)
                    flash("5 wrong attempts — locked out for 30 seconds.", "error")
                    return render_template("login.html"), 429
                flash(f"Wrong or expired code ({int(record['count'])}/5 attempts).", "error")
                return render_template("login.html"), 401
            record.update(count=0, until=0)
        session.clear()
        session["authenticated"] = True
        session["csrf_token"] = secrets.token_urlsafe(24)
        return redirect(url_for("status"))

    @app.route("/healthz")
    def healthz():
        with db_session(app.config["DATABASE"]) as conn:
            conn.execute("SELECT 1").fetchone()
        return jsonify(status="ok")

    @app.route("/logout", methods=["POST"])
    @auth_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        try:
            client_ip = ipaddress.ip_address(request.remote_addr or "")
        except ValueError:
            abort(403)
        if client_ip not in ipaddress.ip_network("192.168.4.0/24") and not app.testing:
            abort(403)
        if request.method == "POST":
            ssid = request.form.get("ssid", "")
            password = request.form.get("password", "")
            ssid_bytes = len(ssid.encode("utf-8"))
            password_bytes = len(password.encode("utf-8"))
            if not 1 <= ssid_bytes <= 32 or not 8 <= password_bytes <= 63 or "\n" in password or "\r" in password:
                flash("Enter an SSID (up to 32 bytes) and a Wi-Fi password of 8 to 63 bytes.", "error")
            else:
                try:
                    wifi_configurator(ssid, password)
                except (OSError, subprocess.SubprocessError) as exc:
                    logger.error("WIFI-001 Wi-Fi configuration failed: %s", exc)
                    flash("Wi-Fi configuration failed; check Diagnostics.", "error")
                else:
                    with db_session(app.config["DATABASE"]) as conn:
                        SettingsRepo(conn).set("wifi_ssid", ssid)
                    flash(f"Connecting to {ssid}. Rejoin that network to continue.", "ok")
        return render_template("setup.html")

    @app.route("/status", methods=["GET", "POST"])
    @auth_required
    def status():
        if request.method == "POST":
            session["live_position"] = request.form.get("action") == "start"
            return redirect(url_for("status"))
        with db_session(app.config["DATABASE"]) as conn:
            values = StateRepo(conn).all()
        return render_template("status.html", state=values, live=session.get("live_position", False))

    @app.route("/catalog")
    @auth_required
    def catalog():
        with db_session(app.config["DATABASE"]) as conn:
            repo = CatalogRepo(conn)
            catalogs = [(row, repo.list_items(row["id"])) for row in repo.list_catalogs()]
        return render_template("catalog.html", catalogs=catalogs)

    @app.route("/catalog/create", methods=["POST"])
    @auth_required
    def catalog_create():
        name = request.form.get("name", "").strip()
        if not name or len(name) > 80: abort(400, "Catalog name is required and must be at most 80 characters")
        try:
            with db_session(app.config["DATABASE"]) as conn: CatalogRepo(conn).create_catalog(name)
        except sqlite3.IntegrityError:
            flash("A catalog with that name already exists.", "error")
        return redirect(url_for("catalog"))

    @app.route("/catalog/<int:catalog_id>/rename", methods=["POST"])
    @auth_required
    def catalog_rename(catalog_id: int):
        name = request.form.get("name", "").strip()
        if not name or len(name) > 80: abort(400)
        try:
            with db_session(app.config["DATABASE"]) as conn:
                repo = CatalogRepo(conn)
                if repo.get_catalog(catalog_id) is None: abort(404)
                repo.rename_catalog(catalog_id, name)
        except sqlite3.IntegrityError:
            flash("A catalog with that name already exists.", "error")
        return redirect(url_for("catalog"))

    @app.route("/catalog/<int:catalog_id>/delete", methods=["POST"])
    @auth_required
    def catalog_delete(catalog_id: int):
        with db_session(app.config["DATABASE"]) as conn:
            repo = CatalogRepo(conn)
            if repo.get_catalog(catalog_id) is None: abort(404)
            repo.delete_catalog(catalog_id)
        return redirect(url_for("catalog"))

    @app.route("/catalog/<int:catalog_id>/items", methods=["POST"])
    @auth_required
    def item_add(catalog_id: int):
        name = request.form.get("name", "").strip()
        if not name or len(name) > 120: abort(400)
        with db_session(app.config["DATABASE"]) as conn:
            repo = CatalogRepo(conn)
            if repo.get_catalog(catalog_id) is None: abort(404)
            repo.add_item(catalog_id, name, request.form.get("ra", "").strip(), request.form.get("dec", "").strip(), request.form.get("type", "").strip(), request.form.get("note", "").strip())
        return redirect(url_for("catalog"))

    @app.route("/catalog/items/<int:item_id>/delete", methods=["POST"])
    @auth_required
    def item_delete(item_id: int):
        with db_session(app.config["DATABASE"]) as conn:
            repo = CatalogRepo(conn)
            if repo.get_item(item_id) is None: abort(404)
            repo.delete_item(item_id)
        return redirect(url_for("catalog"))

    @app.route("/catalog/items/<int:item_id>/edit", methods=["POST"])
    @auth_required
    def item_edit(item_id: int):
        name = request.form.get("name", "").strip()
        if not name or len(name) > 120: abort(400)
        with db_session(app.config["DATABASE"]) as conn:
            repo = CatalogRepo(conn)
            if repo.get_item(item_id) is None: abort(404)
            repo.update_item(item_id, name, request.form.get("ra", "").strip(), request.form.get("dec", "").strip(), request.form.get("type", "").strip(), request.form.get("note", "").strip())
        return redirect(url_for("catalog"))

    @app.route("/catalog/<int:catalog_id>/import", methods=["POST"])
    @auth_required
    def catalog_import(catalog_id: int):
        upload = request.files.get("file")
        if upload is None: abort(400, "Choose a CSV file")
        try:
            decoded = upload.read().decode("utf-8-sig", errors="strict")
            rows = list(csv.reader(io.StringIO(decoded, newline=""), strict=True))
        except (UnicodeDecodeError, csv.Error):
            abort(400, "The upload must be valid UTF-8 CSV")
        items: list[tuple[str, str, str, str, str]] = []
        for number, row in enumerate(rows, start=1):
            if number == 1 and row and row[0].strip().casefold() == "name":
                continue
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) > 5:
                abort(400, f"CSV row {number} has more than five columns")
            values = [value.strip() for value in row] + [""] * (5 - len(row))
            if not values[0] or len(values[0]) > 120:
                abort(400, f"CSV row {number} has an invalid object name")
            if any(len(value) > 1000 for value in values[1:]):
                abort(400, f"CSV row {number} contains an overlong field")
            items.append((values[0], values[1], values[2], values[3], values[4]))
        with db_session(app.config["DATABASE"]) as conn:
            repo = CatalogRepo(conn)
            if repo.get_catalog(catalog_id) is None: abort(404)
            repo.add_items(catalog_id, items)
        flash(f"Imported {len(items)} object(s).", "ok")
        return redirect(url_for("catalog"))

    @app.route("/settings", methods=["GET", "POST"])
    @auth_required
    def settings():
        editable = ("latitude", "longitude", "elevation_m", "timezone", "park_mode", "park_alt", "park_az")
        with db_session(app.config["DATABASE"]) as conn:
            repo = SettingsRepo(conn)
            if request.method == "POST":
                for key in editable: repo.set(key, request.form.get(key, "").strip())
                for name in HARDWARE_COMPONENTS:
                    repo.set(f"hw_sim_{name}", "1" if request.form.get(f"hw_sim_{name}") == "1" else "0")
                flash("Settings saved. Restart the controller for hardware changes to take effect.", "ok")
                return redirect(url_for("settings"))
            values = repo.all()
        return render_template("settings.html", settings=values, hardware_components=HARDWARE_COMPONENTS)

    @app.route("/diagnostics")
    @auth_required
    def diagnostics():
        try:
            log_text = subprocess.run(
                ["journalctl", "-u", "japyscope-app", "-u", "japyscope-webui", "-n", "100", "--no-pager"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            log_text = f"Diagnostics unavailable: {exc}"
        return render_template("diagnostics.html", logs=log_text)

    @app.route("/system", methods=["GET", "POST"])
    @auth_required
    def system():
        commands = {
            "restart-controller": ["sudo", "systemctl", "restart", "japyscope-app.service"],
            "wifi-setup": ["sudo", "/usr/local/sbin/japyscope-wifi-ap", "--force"],
            "reboot": ["sudo", "systemctl", "reboot"],
            "poweroff": ["sudo", "systemctl", "poweroff"],
        }
        if request.method == "POST":
            action = request.form.get("action", "")
            if action in commands:
                action_runner(commands[action]); flash(f"System action queued: {action}.", "ok")
            else: abort(400)
            return redirect(url_for("system"))
        return render_template("system.html")

    if os.environ.get("JAPYSCOPE_DEV_MODE") == "1":
        @app.cli.command("gen-code")
        def gen_code_command():
            """Dev/test only (requires JAPYSCOPE_DEV_MODE=1): generate a
            Web UI access code over SSH, without the physical e-ink
            controller. Mirrors exactly what Menu -> Wi-Fi / Web Access
            does on real hardware (firmware/ui/controller.py) — a random
            6-digit code, valid 10 minutes."""
            code = f"{secrets.randbelow(900000) + 100000}"
            with db_session(app.config["DATABASE"]) as conn:
                AccessCodeRepo(conn).issue(code, 600)
            print(f"Web UI access code: {code} (valid 10 minutes)")

    return app


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="JapyScope Remote Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db")
    args = parser.parse_args(argv)
    create_app(args.db).run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
