"""Live OneWili panel test with explicitly marked synthetic radio values."""
from pathlib import Path
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))

from pwnagotchi import utils, plugins
from pwnagotchi.ui import fonts
from pwnagotchi.ui.display import Display

config = utils.merge_config(
    tomllib.loads((ROOT / 'config/config.toml').read_text()),
    tomllib.loads((ROOT / 'runtime/pwnagotchi/defaults.toml').read_text()))
fonts.init(config)
plugins.load(config)
display = Display(config, state={'name': 'FreeWili>', 'status': 'DISPLAY TEST - NO RADIO',
                                'channel': '--', 'aps': '--', 'shakes': '--'})
plugin = plugins.loaded['freewili']
try:
    display.update(force=True)
    if not plugin.connected.wait(20):
        raise SystemExit('OneWili panel did not connect')
    time.sleep(2)
    print('PASS: upstream Pwnagotchi frame rendered; OneWili panel initialized and updated')
finally:
    plugin.on_unload(display)
