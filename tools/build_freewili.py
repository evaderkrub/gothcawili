"""Build the paired 20 MHz MAIN/FPGA recovery firmware in an isolated copy.

Requires Yosys, nextpnr-ice40 with UP5K chipdb, icepack, CMake/Ninja and Pico SDK
2.3.0 / Arm GNU 14_2_Rel1. Never flashes hardware. See README before deployment.
"""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'ed1b6d359ece87b526d6a62816281c5931d650ce'


def run(*args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--jobs', default='4')
    args = parser.parse_args()
    revision = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise RuntimeError('Review recovery patch against source revision ' + revision)
    stage = ROOT / 'dist/freewili-build'
    if stage.exists():
        raise RuntimeError('Build directory already exists; preserve or remove it before rebuilding')
    def ignore(directory, names):
        return [n for n in names if n in ('.git', 'testprojects', 'Examples', '__pycache__')
                or n.startswith(('build', 'cmake-build'))]
    shutil.copytree(args.source / 'freewilimain', stage / 'freewilimain', ignore=ignore, symlinks=True)
    shutil.copytree(args.source / 'shared', stage / 'shared')
    shutil.copytree(args.source / 'freewilimain/testprojects/onewili/rthon',
                    stage / 'freewilimain/testprojects/onewili/rthon')
    fpga = stage / 'freewilifpga/fpga'
    shutil.copytree(args.source / 'freewilifpga/fpga/src', fpga / 'src')
    shutil.copy2(args.source / 'freewilifpga/fpga/fw.pcf', fpga / 'fw.pcf')
    # Dropbox source snapshots may use CRLF; normalize only the patched files.
    patch = ROOT / 'compat/freewili-bridge.patch'
    for line in patch.read_text().splitlines():
        if line.startswith('--- a/'):
            path = stage / line[6:]
            path.write_text(path.read_text(), newline='\n')
    run('patch', '-p1', '-i', patch, cwd=stage)
    (fpga / 'build').mkdir()
    run('yosys', '-p', 'read_verilog -I. src/dsn/*.v; synth_ice40 -abc9 -device u -top main -json build/hardware.json', cwd=fpga)
    run('nextpnr-ice40', '--up5k', '--package', 'sg48', '--json', 'build/hardware.json',
        '--pcf', 'fw.pcf', '--asc', 'build/hardware.asc', '--freq', '20',
        '--report', 'build/timing.json', cwd=fpga)
    run('icepack', 'build/hardware.asc', 'build/hardware.bin', cwd=fpga)
    data = (fpga / 'build/hardware.bin').read_bytes()
    header = stage / 'freewilimain/fpgabitstreams/fpga_bit_default_v5.h'
    header.write_text('#define FPGA_BITFILE_SIZE %d\nunsigned char const btFPGABit[FPGA_BITFILE_SIZE] = {\n' % len(data)
                     + '\n'.join(','.join('0x%02X' % v for v in data[i:i+16]) + ','
                                 for i in range(0, len(data), 16)) + '\n};\n')
    run('cmake', '-S', stage / 'freewilimain', '-B', stage / 'build', '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Release', '-DPICO_SDK_PATH=' + str(args.sdk.resolve()),
        '-DPICO_TOOLCHAIN_PATH=' + str(args.toolchain.resolve()))
    run('cmake', '--build', stage / 'build', '--target', 'FW2Main', '-j', args.jobs)
    output = ROOT / 'dist/firmware'
    output.mkdir(exist_ok=True)
    shutil.copy2(stage / 'build/targets/fw2main/FW2Main.uf2', output / 'FW2Main.uf2')
    shutil.copy2(fpga / 'build/hardware.bin', output / 'cm0-recovery.bin')
    shutil.copy2(fpga / 'build/timing.json', output / 'timing.json')
    print('Built MAIN UF2. Deploy with scripts/bridge_clock.py as a paired update.')


if __name__ == '__main__':
    main()
