# japyscope-remote

JapyScope Remote — a custom Raspberry Pi Zero W hand controller replacing
the stock SynScan hand controller on a Sky-Watcher Flextube 400P Dobson
mount, plus its companion Web UI. Connects directly to the mount's RJ12
Hand Control port and drives INDI's Sky-Watcher Alt-Az mount driver
directly.

- **Architecture, decisions, and current build status**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Interactive UX mockup**: [docs/index.html](docs/index.html) (published via GitHub Pages)
- **Wiring/pinout**: [docs/WIRING.md](docs/WIRING.md)
- **On-device codes reference**: [docs/CODES.md](docs/CODES.md)

## Status

Firmware v0 is under active development, before any hardware exists yet.
See `docs/ARCHITECTURE.md` for exactly what's implemented vs. still open.

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
