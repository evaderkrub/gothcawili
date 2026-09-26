# GothcWili

Pwnagotchi on the Raspberry Pi CM0 inside FreeWili 2, using a NETGEAR A6150 or TP-Link Archer T3U AC1300 on
the CM0 USB host port and the OneWili API for the built-in display and keypad.

This is an integration of **evilsocket/pwnagotchi 1.5.5**, pinned at
`9034d55d4d69c98fdd50cdf7ecd698a3248975a4`. It runs on the device's existing
64-bit Debian 13 installation. It does not replace the FreeWili firmware.

## Hardware status on FX0106

Validated on 2026-09-26 with **TP-Link Archer T3U (2357:012d)**:

- MAIN and DISPLAY updated to the matching repository-root builds from September
  26; MAIN returned from its fused UF2 loader and DISPLAY passed flash verification.
  The SD recovery copies were updated after backing up the original files.
- CM0 bridge rebuilt from current local sources, with matching OneWili Python
  bindings. The original bridge and SDK are backed up on CM0 under
  `/home/pi/gothcwili-backup-2026-09-26/`.
- USB host mode verified after reboot: the T3U enumerates on CM0 as `wlan0`, using
  the existing `rtw88_8822bu` driver and firmware. Wi-Fi country is US.
- Live Pwnagotchi/bettercap operation verified on monitor interface `pwn0`:
  26 access points detected, received packets increasing, and no service restarts.
  The initial validation used passive mode; see the AI/mesh completion section below.
- The built-in screen was verified from a device screenshot, including face,
  AP counts, uptime, and passive-mode status. The service is enabled at Linux boot, verified with a second reboot.
- Fixed upstream's unconditional mesh advertisement update, which otherwise
  killed the statistics thread when the disabled mesh daemon was absent.
- Installation records and firmware hashes: `reports/fx0106-2026-09-26/`.

This updates MAIN, DISPLAY and the CM0 bridge/SDK. It does not claim updates to
PIC, ESP32, LoRa, or debug-probe firmware. The installed Linux kernel remains
`6.12.75+rpt-rpi-v8`; the whole OS was not upgraded.

## Hardware status on FX0103

Validated on 2026-09-25:

- CM0: Raspberry Pi Compute Module 0 Rev 1.0, aarch64,
  kernel `6.12.75+rpt-rpi-v8`, Python 3.13.5, approximately 416 MiB usable RAM.
- OneWili CM0: live Device State requests and panel/control updates succeeded
  through `fwcm0 api` and the FPGA mailbox.
- CM0 USB: changed from gadget to host mode; rebooted and confirmed the DWC2
  USB root hub and mux GPIO2=1, GPIO3=1. MAIN USB remains available to the PC.
- Dependency installation completed; `dpkg --audit` reported no problems.
  bettercap 2.33.0 and upstream Pwnagotchi imports work on ARM64.
- The **adapter is not enumerating**: `lsusb` currently lists only the root hub.
  Monitor-mode reception, injection, and end-to-end operation are **not yet
  verified**. The A6150 driver (`rtw88_8822bu`) and firmware are already installed.
- The service is installed but stopped and not enabled at boot.

## AI and mesh completion

The port now uses **CPU PyTorch 2.6 / Stable Baselines3 2.6.0 / Gymnasium 1.1.1**
with a compact A2C MLP policy. This replaces the incompatible TensorFlow 1.13 /
Stable Baselines 2 backend. It is **not the original recurrent LSTM**; old
TensorFlow models cannot be loaded. The checkpoint is
`/var/lib/gothcwili/brain-a2c.zip`, with training statistics alongside it.
Training runs on one CPU thread. Checkpoints are written atomically and retain
optimizer state and training counters.

Local peer discovery/advertising uses patched **pwngrid v1.11.6**, supervised with
bettercap and the agent. Its API binds only to `127.0.0.1:8666`; cloud enrollment,
reporting and automatic updates remain disabled. The existing device identity
is preserved. The screen reports AI STARTING, READY or LEARNING.

Association and deauthentication remain off by default. Active mode requires an
explicit list of authorized, exact unicast BSSIDs in `main.allowed_bssids`.
Both active operations enforce that list independently; AI cannot expand it.
An empty list prevents active startup. Set your legal country on the CM0 before
changing the non-DFS channel pool (`ai.channels`); changing the pool changes the
model action space and requires a separate checkpoint path.

All four AI/scope tests passed on the CM0 itself, including real gradient
updates, checkpoint reload/continued training, Gymnasium observations and 5 GHz
histogram bounds. Fourteen host integration tests also pass, including USB re-enumeration detection and USB-mode changes that preserve the bridge clock.

**Hardware validation (2026-09-26):** the T3U enumerates after replugging and
reinitializing the DISPLAY port-control state. Passive reception passed on
channels 1, 6, 11, 36, 44, 149 and 157. Live AI completed gradient updates and
saved its checkpoint. Observed use reached 329 MiB RAM in an earlier run and 287 MiB swap during
final validation; allow 2–3 minutes for cold AI startup on this CM0.

The released mesh encoder emitted an invalid four-byte radiotap header.
`compat/pwngrid.patch` supplies the required bitmap, fixes typed channel/RSSI
extraction, and preserves packet-write errors. Packet round-trip/checksum tests
pass, as does bidirectional simulated peer discovery on channels 1 and 36 using
`tools/mesh_smoke.py`. Simulation does not establish physical over-the-air peer
interoperability; that requires a second device.

Local capture decoded 34/34 own mesh advertisements after installing the patch;
monitor-interface TX counters remained zero, so this is not proof of RF delivery.
The adapter and US regulatory setting persisted through reboot. The earlier
warm-reboot bridge stall is fixed in `compat/freewili-bridge.patch`: the FPGA
router now waits for the encoder to finish CRC/COBS output before starting
another response. The regression fails the original router and passes the fix,
including UART backpressure. The previous 31.25 MHz FPGA clock did not meet
static timing; the paired recovery build uses 20 MHz (22.96 MHz achieved),
2 MHz MAIN register SPI, 4 MHz CM0 SPI and a 5 Mbaud CM0 UART with an 80 MHz
UART source clock. Three consecutive warm reboots passed without a bridge restart.

The supervisor also detects USB disappearance or a changed interface index and
restarts the radio stack, including when Linux reuses the name `wlan0`.
A controlled USB unbind/rebind test passed: disappearance was observed, the
interface index changed, and the service recovered automatically. This tests
software hotplug recovery, not every possible port-power fault.

`tools/radio_lab.py` passed on three isolated mac80211_hwsim radios on channels
1 and 36: real Agent association/deauthentication calls, captured deauth frames,
WPA2 EAPOL exchanges saved by bettercap, and blocked out-of-scope targets.
The lab enables repeat operations after an acquired handshake only in its
private bettercap instance. It stops the production service and never selects
the physical radio; results do not certify physical adapter injection.

A subsequent host-owned WPA2 AP test on channel 6 passed physical association
injection: the AC1300 captured two successful responses from the host AP after
`Agent.associate`. See `reports/host-ap-2026-09-26/`. Full physical handshake
and deauthentication/reconnect validation still require a connected lab client;
5 GHz injection and independent over-the-air mesh reception remain unverified.

Device validation records are under `reports/completion-2026-09-26/`,
`reports/replug-2026-09-26/` and `reports/full-support-2026-09-26/`.
`sudo /opt/gothcwili-venv/bin/python /opt/gothcwili/scripts/health.py` prints a
credential-free snapshot, including USB detection and checkpoint counters.

## Run on CM0

Plug the A6150 or Archer T3U into **Linux USB Host / Port 3 / CN25**, then in the fwcom Linux
Console using the **Main connection**:

```sh
lsusb                         # expect 0846:9055 (A6150) or 2357:012d (T3U)
python3 /opt/gothcwili/run.py --probe
sudo systemctl start gothcwili
sudo journalctl -u gothcwili -f
```

The launcher identifies the adapter by its USB ID, verifies monitor-mode
capability, creates `pwn0`, starts bettercap on loopback, then launches
Pwnagotchi. The native screen shows its face, channels, AP count, uptime,
handshake count and status. Press **red** or **keypad X** to stop. To stop from
Linux, use `sudo systemctl stop gothcwili`. The launcher stops all three child processes,
removes its monitor interface and restores the adapter's NetworkManager state.

Once hardware operation has been verified:

```sh
sudo systemctl enable gothcwili
```

Settings: `/etc/gothcwili/config.toml`. Logs:
`/var/log/gothcwili/{pwnagotchi,bettercap,pwngrid}.log`. Captures and identity:
`/var/lib/gothcwili/`. Configuration changes survive reinstallation.

Use the radio on networks you own or are authorized to test. Test capture and
any desired transmit behavior against a lab AP before changing the passive
defaults. The configured pool covers 2.4 GHz and non-DFS 5 GHz. DFS is excluded.

## Build and install on another CM0

The CM0 must already have the matching FreeWili bridge, generated OneWili
Python package, `onewili_cm0`, and firmware supporting `fwcm0 api` and the panel
button API. The installed device SDK includes newer firmware-matched changes
than the current public OneWili checkout; do not replace it with an older SDK.

```powershell
git clone --single-branch --branch master https://github.com/evilsocket/pwnagotchi.git .upstream/pwnagotchi
git -C .upstream/pwnagotchi checkout 9034d55d4d69c98fdd50cdf7ecd698a3248975a4
python tools/bundle.py
python -m unittest discover -s tests -p test_integration.py -v
# In an environment containing the pinned AI dependencies:
python tests/test_ai_runtime.py -v
git clone https://github.com/jayofelony/pwngrid.git .upstream/pwngrid
git -C .upstream/pwngrid checkout 913a03fe53d9ae69e70ff070c9d35c6ada071e9c
# Run on ARM64 with Go >=1.25 and libpcap-dev, or supply a CGO cross toolchain:
python tools/build_pwngrid.py
```

Install the packages listed in `scripts/install-dependencies.sh` on CM0. Copy
`dist/gothcwili.tar.gz` and `dist/pwngrid-fixed/pwngrid` onto it, then:

```sh
sudo install -m755 pwngrid /usr/local/bin/pwngrid
sudo mkdir -p /opt/gothcwili
sudo tar -xzf gothcwili.tar.gz -C /opt/gothcwili
sudo python3 /opt/gothcwili/scripts/install.py
sudo python3 /opt/gothcwili/scripts/usb_host.py
sudo reboot
```

For an existing passive installation, after installing the new dependencies
and runtime, run `sudo python3 /opt/gothcwili/scripts/enable_ai.py` and restart
the service. It backs up the configuration, preserves the bettercap password,
and enables AI/local mesh with active operations disabled.

The build copies the pinned upstream source into `runtime/` and applies the
reviewable compatibility replacements in `tools/prepare_runtime.py`:
removed `distutils` API, Debian's `Cryptodome` namespace, modern WebSockets and
asyncio setup, Flask startup, bounded HTTP requests, `iw` PHY channel discovery,
and local state paths. Upstream's system installer is never executed.

`scripts/display_test.py` exercises the real upstream UI and OneWili panel
without a Wi-Fi adapter, showing `DISPLAY TEST - NO RADIO`. A successful API
reply alone does not establish that the final panel is visible; inspect the
screen when validating firmware versions.

## MAIN/FPGA bridge recovery build

FX0106 runs the custom MAIN/FPGA recovery image built from FreeWili firmware
revision `ed1b6d359ece87b526d6a62816281c5931d650ce`. DISPLAY remains the
matching September 26 build. This is a tested local build, not a claim that
all auxiliary PIC/probe/ESP/WIO firmware has been updated.

With Yosys 0.52, nextpnr-ice40 0.7 plus UP5K chipdb, icepack, CMake/Ninja,
Pico SDK 2.3.0 and Arm GNU 14_2_Rel1 available:

```sh
python tools/build_freewili.py --source /path/to/freewili-firmware --sdk /path/to/pico-sdk/2.3.0 --toolchain /path/to/toolchain/14_2_Rel1
```

The builder works in an isolated copy and rejects timing failures. It emits
`dist/firmware/FW2Main.uf2`, the gateware and timing report. It does not flash.
Install this MAIN image **together with** the CM0 settings from
`scripts/bridge_clock.py`, then reboot CM0. Use the partition-aware **FW2Main
FBL** loader and the MAIN UF2; never write a raw ELF/BIN over the fused loader.
Preserve the existing image and boot files before updating.

For rollback, restore both original MAIN firmware and the files
`/boot/firmware/config.txt.before-gothcwili-clock` and
`/etc/environment.before-gothcwili-clock`, then reboot. Restore the USB host
configuration afterward if the backup predates host mode. Do not mix the
original UART settings with the new FPGA image. USB gadget/host switching via
`usb_host.py` preserves the currently selected UART clock.

## PC tools and recovery

`tools/cm0.py` uses the running fwcom MCP server and its framed Linux shell.
Defaults refer to this PC's local fwcom checkout, MCP configuration and device
FX0103; override with `--fwcom`, `--config`, and `--device` on another PC.
It reads the local MCP token without displaying or copying it.

```powershell
python tools/cm0.py "lsusb; iw dev"
python tools/cm0.py --upload local.py --destination /home/pi/local.py
```

Close any Linux terminal panel/session before opening a new framed shell.
If fwcom is disconnected, `--serial-port COM183` uses MAIN directly. Do not use
that option while the GUI owns the port. The tool never repeats a write with
an uncertain result; it resends only a positively reported unaccepted suffix.

Before host mode, `tools/serial_upload.py FILE /home/pi/FILE --port COM16`
provides a faster transfer through an idle, logged-in CM0 gadget console,
with SHA256 verification. Gadget Serial disappears in host mode; use MAIN
afterward. Offline `.deb` downloads can be prepared with `apt-get --print-uris`
on CM0 and `tools/download_debs.py` on the PC. Refresh stale package metadata
when an exact package version has been removed from the mirror.

Original boot settings are preserved in `/boot/firmware/gothcwili-backup/`.
To restore the CM0 USB serial gadget:

```sh
sudo systemctl stop gothcwili
sudo python3 /opt/gothcwili/scripts/usb_host.py --restore
sudo reboot
```

## References

- [Stable Baselines3 A2C](https://stable-baselines3.readthedocs.io/en/v2.6.0/modules/a2c.html)
- [ARM64 AI migration reference](https://github.com/ex18a/pwnagotchi64)
- [pwngrid release](https://github.com/jayofelony/pwngrid/releases/tag/v1.11.6)
- [Upstream Pwnagotchi](https://github.com/evilsocket/pwnagotchi)
- [OneWili CM0 transport](https://github.com/freewili/onewili/tree/main/cm0)
- [OneWili API](https://freewili.com/onewili/)
- [NETGEAR A6150](https://www.netgear.com/home/wifi/adapters/a6150/)
- [Linux A6150 USB ID mapping](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/realtek/rtw88/rtw8822bu.c)

Pwnagotchi and this integration are GPL-3.0; the upstream license is included
in the runtime bundle. OneWili is installed separately under its own license.
