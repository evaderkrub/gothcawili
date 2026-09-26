"""Exact BSSID scope for optional active radio operations."""
import re


def allowed_bssids(config):
    values = config.get('main', {}).get('allowed_bssids', [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value)
        or int(value[:2], 16) & 1 for value in values
    ):
        raise ValueError('main.allowed_bssids must contain exact unicast BSSIDs')
    return {value.lower() for value in values}


def permitted(config, ap):
    return str(ap.get('mac', '')).lower() in allowed_bssids(config)
