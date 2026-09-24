# japyscope-remote

JapyScope Remote — a custom Raspberry Pi Zero W hand controller for GoTo
telescope mounts (not limited to Dobsonians — developed and tested
against a Sky-Watcher Flextube 400P Dobsonian), plus its companion Web
UI. Connects directly to the mount's RJ12 Hand Control port, currently
replacing the stock SynScan hand controller and driving INDI's
Sky-Watcher Alt-Az mount driver directly.

- **Docs site (wizard + wiki)**: [open the JapyScope documentation](https://jan-tdy.github.io/japyscope-remote/) (published via GitHub Pages/Jekyll)
- **Architecture, decisions, and current build status**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Interactive UX mockup on its own**: [docs/mockup.html](docs/mockup.html)
- **Wiring/pinout**: [docs/WIRING.md](docs/WIRING.md)
- **On-device codes reference**: [docs/CODES.md](docs/CODES.md)

## Status

Firmware v0 is under active development, alongside hardware bring-up
(Fáza 1beta / 1). See `docs/ARCHITECTURE.md` for exactly what's implemented
vs. still open.

The installer supports 32-bit Raspberry Pi OS Lite on the original Pi Zero W:
Bullseye, Bookworm, and Trixie. See [installation](docs/INSTALL.md).

## Development

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

No hardware is required to run the test suite or to develop most of the
firmware — see `firmware/hal/` for the simulator backends used in place of
real GPIO/SPI hardware.
