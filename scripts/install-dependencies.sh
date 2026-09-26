#!/bin/sh
set -eu
# Debian 13 ARM64. The firmware-matched OneWili SDK is provisioned separately.
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
  bettercap python3-scapy python3-flask python3-flask-cors python3-flaskext.wtf \
  python3-toml python3-numpy python3-pil python3-websockets \
  python3-file-read-backwards python3-pycryptodome fonts-dejavu-core iw tcpdump \
  python3-venv python3-torch python3-matplotlib python3-pandas python3-cloudpickle \
  python3-tqdm python3-rich aircrack-ng
sudo python3 -m venv --system-site-packages /opt/gothcwili-venv
sudo /opt/gothcwili-venv/bin/pip install 'stable-baselines3==2.6.0' 'gymnasium==1.1.1' 'Farama-Notifications==0.0.4'
# Install the digest-verified ARM64 pwngrid v1.11.6 release at /usr/local/bin/pwngrid.
