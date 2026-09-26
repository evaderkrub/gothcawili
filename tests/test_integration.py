import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.upstream/pwnagotchi'))

from run import find_adapter, radio_generation
from scripts.usb_host import host_config, gadget_config, usb_cmdline
from tools.cm0 import Shell

spec = importlib.util.spec_from_file_location('freewili_test', ROOT / 'plugins/freewili.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class CaptionTests(unittest.TestCase):
    def test_escape_markers_and_non_ascii(self):
        self.assertEqual(plugin.panel_text('abc#`\n\u2603'), 'abc##``??')

    def test_limit_applies_after_escaping(self):
        for size in range(35):
            result = plugin.panel_text('#' * size)
            self.assertLessEqual(len(result.encode('ascii')), 31)
            self.assertEqual(len(result) % 2, 0)

    def test_unknown_and_known_face(self):
        self.assertEqual(plugin.face_text(plugin.faces.SLEEP), '(-_-) zZ')
        self.assertEqual(plugin.face_text('unknown'), '(o_o)')


class BootTests(unittest.TestCase):
    def test_round_trip_preserves_updated_bridge_clock(self):
        original = '[all]\ndtoverlay=dwc2,dr_mode=peripheral\ngpio=2=op,dl\ngpio=3=op,dh\ninit_uart_clock=80000000\n'
        self.assertEqual(gadget_config(host_config(original)), original)
        self.assertEqual(gadget_config(original), original)
        cmdline = 'root=PARTUUID=123 modules-load=dwc2,g_serial quiet\n'
        self.assertEqual(usb_cmdline(usb_cmdline(cmdline), True), cmdline)
        self.assertEqual(usb_cmdline(cmdline, True), cmdline)

    def test_host_conversion_is_idempotent_and_preserves_uart(self):
        before = '[all]\ndtoverlay=dwc2,dr_mode=peripheral\ngpio=2=op,dl\ngpio=3=op,dh\ninit_uart_clock=125000000\n'
        after = host_config(before)
        self.assertIn('dr_mode=host', after)
        self.assertIn('gpio=2=op,dh', after)
        self.assertIn('init_uart_clock=125000000', after)
        self.assertEqual(after, host_config(after))

    def test_unknown_mux_is_not_modified(self):
        with self.assertRaises(ValueError):
            host_config('[all]\ndtoverlay=dwc2,dr_mode=peripheral\n')


class AdapterTests(unittest.TestCase):
    def test_replug_changes_generation_even_with_same_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, index in [('wlan0', 2), ('pwn0', 3)]:
                (root / name).mkdir()
                (root / name / 'ifindex').write_text(str(index))
            before = radio_generation('wlan0', 'pwn0', root)
            (root / 'pwn0/ifindex').unlink()
            self.assertIsNone(radio_generation('wlan0', 'pwn0', root))
            (root / 'pwn0/ifindex').write_text('7')
            self.assertNotEqual(before, radio_generation('wlan0', 'pwn0', root))

    def make_adapter(self, root, name, vendor, product):
        # A physical USB parent above an interface node, as exposed in sysfs.
        parent = root / name / 'device'
        parent.mkdir(parents=True)
        (parent / 'idVendor').write_text(vendor)
        (parent / 'idProduct').write_text(product)

    def test_selects_usb_identity_not_wlan_number(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_adapter(root, 'wlan0', '1234', '5678')
            self.make_adapter(root, 'wlxabcdef', '0846', '9055')
            self.assertEqual(find_adapter(root), 'wlxabcdef')

    def test_missing_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(find_adapter(Path(folder)))

    def test_archer_t3u(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_adapter(root, 'wlan0', '1234', '5678')
            self.make_adapter(root, 'wlx20e15db1ec02', '2357', '012d')
            self.assertEqual(find_adapter(root), 'wlx20e15db1ec02')

    def test_two_supported_models_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_adapter(root, 'wlan1', '0846', '9055')
            self.make_adapter(root, 'wlan2', '2357', '012d')
            with self.assertRaises(RuntimeError):
                find_adapter(root)

    def test_ambiguous_adapter_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('wlan1', 'wlan2'):
                self.make_adapter(root, name, '0846', '9055')
            with self.assertRaises(RuntimeError):
                find_adapter(root)


class ShellTests(unittest.TestCase):
    def test_short_writes_send_only_remaining_suffix(self):
        shell = Shell(None, 'test')
        seen = []
        def call(operation, **arguments):
            data = bytes.fromhex(arguments['data'])
            count = min(3, len(data))
            seen.append(data[:count])
            return {'accepted': count}
        shell.call = call
        data = b'0123456789' * 25
        shell.write(data)
        self.assertEqual(b''.join(seen), data)

    def test_uncertain_write_is_never_replayed(self):
        shell = Shell(None, 'test')
        attempts = []
        def call(*args, **kwargs):
            attempts.append(kwargs)
            raise TimeoutError('reply lost')
        shell.call = call
        with self.assertRaises(TimeoutError):
            shell.write(b'echo hello\n')
        self.assertEqual(len(attempts), 1)


if __name__ == '__main__':
    unittest.main()
