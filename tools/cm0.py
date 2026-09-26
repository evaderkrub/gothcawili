"""Run commands on CM0 through the already-running fwcom MCP connection.

Uses fwcom's own Python MCP client. Credentials stay in the local fwcom config.
"""
import argparse
import base64
import json
import re
from pathlib import Path
import secrets
import shlex
import sys
import time


class Shell:
    def __init__(self, gui, device):
        self.gui = gui
        self.device = device
        self.session = secrets.randbits(32) or 1

    def call(self, operation, **arguments):
        return self.gui.freewili.command(
            self.device, 'linux_' + operation + '_shell_session',
            session=self.session, **arguments)['result']

    def __enter__(self):
        self.call('open')
        # MAIN acknowledges ownership before the CM0 starts its login shell.
        # Sending immediately can discard the first command during boot/login.
        try:
            output = bytearray()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                output.extend(self.read())
                if b'$' in output or b'#' in output:
                    return self
                time.sleep(.05)
            raise TimeoutError('CM0 did not present a shell prompt')
        except BaseException:
            self.call('close')
            raise
        return self

    def __exit__(self, *exc):
        self.call('close')
        # MAIN emits the deferred detach on its next (up to 100 ms) mailbox tick.
        time.sleep(.25)

    def read(self):
        result = self.call('read', maximum=192)
        data = bytes.fromhex(result['data']) if result['count'] else b''
        if len(data) != result['count']:
            raise RuntimeError('Invalid CM0 shell output length')
        return data

    def write(self, data):
        deadline = time.monotonic() + 60
        while data:
            chunk = data[:192]
            result = self.call('write', data=chunk.hex())
            count = result['accepted']
            if not 0 <= count <= len(chunk):
                raise RuntimeError('Invalid CM0 accepted byte count')
            data = data[count:]
            if time.monotonic() > deadline:
                raise TimeoutError('CM0 input did not drain; command was not replayed')
            if count == 0:
                time.sleep(.05)

    def run(self, command, timeout=60):
        marker = 'GOTHCWILI_' + secrets.token_hex(12)
        # Hide the marker from the terminal echo so only execution completes it.
        encoded = ''.join('\\%03o' % ord(c) for c in marker)
        self.write((command + "; printf '\\n" + encoded + ":%s\\n' \"$?\"\n").encode())
        output = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.read()
            output.extend(data)
            start = output.find(marker.encode() + b':')
            if start >= 0 and b'\n' in output[start:]:
                status = int(output[start:].splitlines()[0].split(b':')[1])
                return output[:start].decode(errors='replace'), status
            if not data:
                time.sleep(.05)
        raise TimeoutError('CM0 command timed out; partial output:\n' + output.decode(errors='replace'))


class SerialShell(Shell):
    """Same framed protocol when fwcom has disconnected from the MAIN port."""
    def __init__(self, port):
        super().__init__(None, port)
        import serial
        self.port = serial.Serial(port, 1000000, timeout=.05, write_timeout=5)
        self.port.write(b'\x02?\n')
        identity = self._response('?')
        if not identity.startswith('FW2 '):
            self.port.close()
            raise RuntimeError('Expected a FreeWili 2 MAIN port')

    def _response(self, path):
        pending = bytearray()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            pending.extend(self.port.read(max(1, self.port.in_waiting)))
            while b'\n' in pending:
                line, _, pending = pending.partition(b'\n')
                start = line.find(b'[' + path.encode() + b' ')
                if start < 0:
                    start = line.find(b'[\\' + path.encode() + b' ')
                if start < 0:
                    continue
                fields = line[start + 1:].rstrip(b'\r').split(b' ', 3)
                if len(fields) != 4:
                    continue
                body = fields[3]
                if not body.endswith(b' 1]'):
                    raise RuntimeError(body.decode(errors='replace'))
                return body[:-3].decode('ascii')
        raise TimeoutError('No reply to ' + path + '; request was not replayed')

    def call(self, operation, **arguments):
        path = 'l\\' + {'open': 'c', 'close': 'e', 'write': 'w', 'read': 'r'}[operation]
        command = path + ' %08X' % self.session
        if operation == 'write':
            command += ' ' + arguments['data']
        if operation == 'read':
            command += ' ' + str(arguments['maximum'])
        self.port.write(command.encode() + b'\n')
        body = self._response(path)
        if operation == 'read':
            count, data, running = body.split()
            return {'count': int(count), 'data': data, 'running': running == '1'}
        if operation == 'write':
            return {'accepted': int(body)}
        return body

    def __enter__(self):
        try:
            return super().__enter__()
        except BaseException:
            self.port.close()
            raise

    def __exit__(self, *exc):
        try:
            super().__exit__(*exc)
        finally:
            self.port.close()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fwcom', type=Path, default=Path(
        r'C:\~prj\Dropbox\FreeWilli\master\freewili-firmware\freewilimain\testprojects\fwcom'))
    parser.add_argument('--config', type=Path, default=Path(
        r'C:\buildfiles\fwcom\visual-studio\Release\data\plugin-settings\mcp.json'))
    parser.add_argument('--device', default='FX0103')
    parser.add_argument('--serial-port', help='Use MAIN directly only while fwcom is disconnected')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--upload', type=Path)
    parser.add_argument('--destination')
    parser.add_argument('command', nargs='?', default='true')
    args = parser.parse_args()
    from contextlib import ExitStack
    with ExitStack() as stack:
        if args.serial_port:
            shell = stack.enter_context(SerialShell(args.serial_port))
        else:
            sys.path.insert(0, str(args.fwcom / 'plugins/hackrf/python'))
            from fwcom_hackrf.client import Fwcom
            config = json.loads(args.config.read_text())
            gui = stack.enter_context(Fwcom(url='http://127.0.0.1:%s/mcp' % config['port'], token=config['token']))
            shell = stack.enter_context(Shell(gui, args.device))
        if shell:
            # Disable echo for clean output and for uploads larger than a tty line.
            text, code = shell.run("stty -echo; PS1=''; PS2=''; bind 'set enable-bracketed-paste off'", args.timeout)
            if code:
                raise RuntimeError(text)
            if args.upload:
                if not args.destination:
                    parser.error('--upload requires --destination')
                payload = base64.b64encode(args.upload.read_bytes()).decode()
                delimiter = 'UPLOAD_' + secrets.token_hex(12)
                lines = '\n'.join(payload[i:i+256] for i in range(0, len(payload), 256))
                command = "base64 -d > " + shlex.quote(args.destination) + " <<'" + delimiter + "'\n" + lines + '\n' + delimiter + '\n(exit $?)'
            else:
                command = args.command
            text, code = shell.run(command, args.timeout)
            text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
            text = re.sub(r'\x1b\][^\x07]*\x07', '', text)
            print(text.replace('\r', '').strip())
            return code


if __name__ == '__main__':
    sys.exit(main())
