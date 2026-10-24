# japyscope-remote

JapyScope Remote is a custom Raspberry Pi Zero W hand controller for GoTo
telescope mounts.
Can connect via RJ12/Wi-Fi.

<-- TODO: remove or make functional bluetooth -->

To control the mount, it uses INDI.

- **Docs site (wizard + wiki)**: [open the JapyScope documentation](https://jan-tdy.github.io/japyscope-remote/) (published via GitHub Pages/Jekyll)
- **User manual (PDF)**: [docs/JapyScope_Remote_User_Manual.pdf](docs/JapyScope_Remote_User_Manual.pdf)
- **Architecture, decisions, and current build status**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Interactive UX mockup on its own**: [docs/mockup.html](docs/mockup.html)
- **Wiring/pinout**: [docs/WIRING.md](docs/WIRING.md)
- **On-device codes reference**: [docs/CODES.md](docs/CODES.md)

## Status

The installer supports 32-bit Raspberry Pi OS Lite on the original Pi Zero W:
Bullseye, Bookworm, and Trixie. See [installation](docs/INSTALL.md).

## Development (testing)

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

No hardware is required to run the test suite or to develop most of the
firmware — see `firmware/hal/` for the simulator backends used in place of
real GPIO/SPI hardware.
