def mac_offset(mac_address: str, offset: int) -> str:
    mac_int = int(mac_address.replace(':', ''), 16)
    new_mac_int = mac_int + offset
    new_mac_address = f'{new_mac_int:012x}'
    return ':'.join(new_mac_address[i : i + 2] for i in range(0, len(new_mac_address), 2))


def normalize_mac(mac: str) -> str:
    """
    Normalize a MAC address.
    Input: any common MAC format
    Output: XX:XX:XX:XX:XX:XX (uppercase)
    """
    # Remove all separators
    mac_clean = mac.replace(':', '').replace('-', '').replace('.', '').upper()
    if len(mac_clean) != 12:
        raise ValueError(f'Invalid MAC address: {mac}')
    return ':'.join([mac_clean[i : i + 2] for i in range(0, 12, 2)])


def format_mac_to_h3c(mac: str) -> str:
    """
    Convert a MAC address to H3C format.
    Input formats: xx:xx:xx:xx:xx:xx or XX-XX-XX-XX-XX-XX (or with dots)
    Output format: xxxx-xxxx-xxxx (lowercase)
    """
    # Remove all separators
    mac_clean = mac.replace(':', '').replace('-', '').replace('.', '').lower()
    if len(mac_clean) != 12:
        raise ValueError(f'Invalid MAC address: {mac}')
    return f'{mac_clean[0:4]}-{mac_clean[4:8]}-{mac_clean[8:12]}'
