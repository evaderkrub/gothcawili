"""Upload a file through an idle, logged-in CM0 USB gadget shell.

The receiver uses bounded reads and SHA256 verification, then atomically renames
the completed file. MAIN's connection remains open in fwcom.
"""
import argparse
import hashlib
from pathlib import Path
import shlex
import sys
import time

import serial

RECEIVER = r'''
import hashlib,os,select,sys,termios,time,tty
path,size,digest=sys.argv[1],int(sys.argv[2]),sys.argv[3]
fd=sys.stdin.fileno()
old=termios.tcgetattr(fd)
tmp=path+'.upload'
try:
 tty.setraw(fd)
 h=hashlib.sha256()
 print('UPLOAD_READY',flush=True)
 with open(tmp,'wb') as f:
  left=size
  while left:
   block=min(16384,left)
   data=bytearray()
   while len(data)<block:
    if not select.select([fd],[],[],15)[0]: raise TimeoutError('upload stalled')
    part=os.read(fd,block-len(data))
    if not part: raise EOFError('upload closed')
    data.extend(part)
   f.write(data); h.update(data); left-=len(data)
   print('UPLOAD_ACK',flush=True)
 if h.hexdigest()!=digest: raise ValueError('SHA256 mismatch')
 os.replace(tmp,path)
 print('UPLOAD_OK '+digest,flush=True)
finally:
 termios.tcsetattr(fd,termios.TCSANOW,old)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('destination')
    parser.add_argument('--port', default='COM16')
    args = parser.parse_args()
    payload = args.file.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    import base64
    source = base64.b64encode(RECEIVER.encode()).decode()
    command = "python3 -c " + shlex.quote("import base64;exec(base64.b64decode(%r))" % source)
    command += ' ' + shlex.quote(args.destination) + ' ' + str(len(payload)) + ' ' + digest
    with serial.Serial(args.port, 115200, timeout=1, write_timeout=15) as port:
        def wait(marker, timeout=30):
            output = bytearray()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                output.extend(port.read_until(b'\n'))
                if marker in output:
                    return
            raise TimeoutError(output.decode(errors='replace'))
        port.write(b'stty -echo\n')
        time.sleep(.2)
        port.reset_input_buffer()
        port.write(command.encode() + b'\n')
        wait(b'UPLOAD_READY\n')
        start = time.monotonic()
        for offset in range(0, len(payload), 16384):
            port.write(payload[offset:offset+16384])
            wait(b'UPLOAD_ACK\n')
        wait(b'UPLOAD_OK ' + digest.encode())
        port.write(b'stty echo\n')
        print('Uploaded %s bytes in %.1fs; SHA256 %s' % (len(payload), time.monotonic()-start, digest))


if __name__ == '__main__':
    main()
