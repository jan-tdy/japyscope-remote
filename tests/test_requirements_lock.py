import re
from pathlib import Path

LOCK = Path(__file__).resolve().parent.parent / "requirements.lock"
PURE_PYTHON_WHEEL_SHA256 = "6df0ec430f9a831772c23ca5a224cba36517a58a84bb32c32bb59a9fa67c47f6"


def test_charset_normalizer_is_limited_to_the_pure_python_wheel():
    # The compiled armv7l wheels crash with SIGILL on the Pi Zero W's ARMv6 CPU.
    block = re.search(r"^charset-normalizer==\S+ \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", LOCK.read_text(), re.MULTILINE)
    assert block is not None
    assert re.findall(r"sha256:([0-9a-f]{64})", block.group(1)) == [PURE_PYTHON_WHEEL_SHA256]
