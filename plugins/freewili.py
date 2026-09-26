"""Pwnagotchi's live state on a FreeWili 2 panel through OneWili CM0."""
import logging
import os
import signal
import threading
import time
import textwrap

import pwnagotchi.plugins as plugins
import pwnagotchi.ui.faces as faces

BG, FG, ACCENT, MUTED = 0x101820, 0xE8EEF2, 0x62E69A, 0xA9B7C6
KEYS = ('name', 'face', 'channel', 'aps', 'uptime', 'shakes', 'status', 'mode')


def panel_text(value, limit=31):
    """ASCII font; fit the firmware's 31-byte caption after marker escaping."""
    result = ''
    for char in str(value or ''):
        char = char if ' ' <= char <= '~' else '?'
        encoded = char * 2 if char in '#`' else char
        if len(result) + len(encoded) > limit:
            break
        result += encoded
    return result


def face_text(face):
    variants = {
        'SLEEP': '(-_-) zZ', 'SLEEP2': '(-_-) zZ', 'BORED': '(-__-)',
        'SAD': '(T_T)', 'LONELY': '(;_;)', 'ANGRY': '(-_-!)',
        'EXCITED': '(^o^)', 'HAPPY': '(^_^)', 'GRATEFUL': '(^_^)',
        'COOL': '(B_B)', 'BROKEN': '(x_x)', 'SMART': '(+_+)',
    }
    for name, text in variants.items():
        if face == getattr(faces, name, None):
            return text
    return '(o_o)'


class FreeWili(plugins.Plugin):
    __author__ = 'gothcwili'
    __version__ = '0.1.0'
    __license__ = 'GPL-3.0-or-later'
    __description__ = 'CM0 mailbox display and keypad stop for FreeWili 2'

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}
        self._stop = threading.Event()
        self._worker = None
        self.connected = threading.Event()
        self._mode = 'PASSIVE | AI OFF'
        self._radio_mode = 'PASSIVE'
        self._ai_state = 'OFF'

    def on_config_changed(self, config):
        active = config['personality']['deauth'] or config['personality']['associate']
        with self._lock:
            self._radio_mode = 'ACTIVE' if active else 'PASSIVE'
            self._ai_state = 'STARTING' if config['ai']['enabled'] else 'OFF'
            self._mode = self._radio_mode + ' | AI ' + self._ai_state

    def _set_ai(self, state):
        with self._lock:
            self._ai_state = state
            self._mode = self._radio_mode + ' | AI ' + state

    def on_ai_ready(self, agent):
        self._set_ai('READY')

    def on_ai_training_start(self, agent, epochs):
        self._set_ai('LEARNING')

    def on_ai_training_end(self, agent):
        self._set_ai('READY')

    def on_loaded(self):
        if self._worker is None or not self._worker.is_alive():
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()

    def on_ui_update(self, ui):
        values = {key: ui.get(key) for key in KEYS}
        with self._lock:
            self._state = values

    def on_unload(self, ui):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=10)

    def _setup(self, dev):
        # SHOW_PANEL emits a panel-show event. Let MAIN's current app finish its
        # initial repaint before replacing the shared custom panel and controls.
        dev.gui.panels.show_panel(0).unwrap()
        time.sleep(.3)
        dev.gui.panels.add_panel(False, 0, BG, True).unwrap()
        dev.gui.panels.set_menu_text(4, 'Stop').unwrap()
        # Each dynamic item has its own control; only changed captions cross the link.
        rows = [(0, 20, 14, 0, ACCENT, 'PWNAGOTCHI'),
                (1, 20, 49, 0, MUTED, 'CM0  |  USB AC1300'),
                (2, 20, 95, 3, FG, '(o_o)'),
                (3, 240, 88, 0, FG, 'CH --  APS --'),
                (4, 240, 113, 0, FG, 'UP 00:00:00'),
                (5, 240, 138, 0, ACCENT, 'PWND 0'),
                (6, 20, 190, 0, FG, 'Starting Pwnagotchi...'),
                (7, 20, 214, 0, FG, ''),
                (8, 20, 247, 0, MUTED, 'PASSIVE | AI OFF'),
                (9, 20, 270, 0, MUTED, 'Red / X: stop')]
        for index, x, y, size, color, caption in rows:
            dev.gui.controls.add_text(index, x, y, 0, size, color, BG, caption).unwrap()

    def _run(self):
        from onewili_cm0 import connect_cm0
        while not self._stop.is_set():
            dev = None
            try:
                dev = connect_cm0(timeout=8)
                self._setup(dev)
                previous = {}
                self.connected.set()
                logging.info('FreeWili LCD connected through OneWili CM0')
                while not self._stop.wait(.5):
                    with self._lock:
                        state = dict(self._state)
                        mode = self._mode
                    status = textwrap.wrap(str(state.get('status') or 'Starting...'), width=31)
                    captions = {
                        2: face_text(state.get('face')),
                        3: 'CH %s  APS %s' % (state.get('channel') or '--', state.get('aps') or '0'),
                        4: 'UP %s' % (state.get('uptime') or '00:00:00'),
                        5: 'PWND %s' % (state.get('shakes') or '0'),
                        6: status[0] if status else '',
                        7: status[1] if len(status) > 1 else '',
                        8: mode,
                    }
                    for index, value in captions.items():
                        value = panel_text(value)
                        if previous.get(index) != value:
                            dev.gui.control_properties.set_control_value_text(index, value).unwrap()
                            previous[index] = value
                    buttons = dev.gui.panels.read_buttons().unwrap()
                    if buttons & ((1 << 4) | (1 << 11)):
                        dev.gui.control_properties.set_control_value_text(6, 'Stopped').unwrap()
                        dev.gui.control_properties.set_control_value_text(7, 'Start: sudo systemctl start').unwrap()
                        dev.gui.control_properties.set_control_value_text(9, 'gothcwili').unwrap()
                        logging.info('Stopped with FreeWili keypad')
                        os.kill(os.getpid(), signal.SIGTERM)
                        return
            except Exception:
                logging.exception('FreeWili display unavailable; retrying in 5s')
                self._stop.wait(5)
            finally:
                self.connected.clear()
                if dev is not None:
                    dev.close()
