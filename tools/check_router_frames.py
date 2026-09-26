"""Validate COBS and CRC of the three frames emitted by router_backpressure.v."""
import sys


def decode(data):
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        if not code or i + code > len(data):
            raise ValueError('Malformed COBS block')
        out.extend(data[i + 1:i + code])
        i += code
        if code != 255 and i < len(data):
            out.append(0)
    return bytes(out)


def main():
    data = bytes(int(line.split()[1], 16) for line in sys.stdin if line.startswith('BYTE '))
    frames = [decode(block) for block in data.split(b'\0') if block]
    expected = [(3, 0, b'\1'), (5, 0, b'BC'), (2, 0x27, b'\xc0\0\0\0\0\0')]
    assert len(frames) == len(expected)
    for frame, (kind, sequence, payload) in zip(frames, expected):
        assert frame[:4] == bytes([kind, sequence, 0, len(payload)])
        assert frame[4:-1] == payload
        crc = 0
        for value in frame[:-1]:
            crc ^= value
            for _ in range(8):
                crc = ((crc << 1) ^ (7 if crc & 128 else 0)) & 255
        assert crc == frame[-1]
    print('PASS: boot notification, mailbox and status payloads with valid COBS/CRC')


if __name__ == '__main__':
    main()
