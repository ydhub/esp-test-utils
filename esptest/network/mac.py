def mac_offset(mac_address: str, offset: int) -> str:
    mac_int = int(mac_address.replace(':', ''), 16)
    new_mac_int = mac_int + offset
    new_mac_address = f'{new_mac_int:012x}'
    return ':'.join(new_mac_address[i : i + 2] for i in range(0, len(new_mac_address), 2))
