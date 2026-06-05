import serial

import esptest.common.compat_typing as t

from .serial_tools import compute_serial_port, get_all_serial_ports


def get_tempbox_port(port: str = '') -> str:
    """Return port.device if tempbox is connected."""
    if port:
        return compute_serial_port(port, strict=False)
    for p in get_all_serial_ports():
        if p.vid == 0x0403 and p.pid == 0x6001:
            return p.device  # type: ignore
        if p.vid == 0x1A86 and p.pid == 0x7523:
            return p.device  # type: ignore
    return ''


def _modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _build_request(addr: int, func_code: int, payload: bytes) -> bytes:
    frame = bytes([addr, func_code]) + payload
    crc = _modbus_crc(frame)
    return frame + crc.to_bytes(2, byteorder='little')


def _d_register_to_addr(register: str) -> int:
    register = register.upper()
    if not register.startswith('D'):
        raise ValueError(f'Invalid register: {register}')
    return int(register[1:])


def _to_signed_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


class TempboxController:
    """Generic U680 tempbox controller via Modbus RTU."""

    TEMPBOX_BAUDRATE = 9600  # serial port baudrate
    TEMPBOX_TIMEOUT = 1  # serial port read timeout, using serial.read directly now
    MODBUS_FUNC_READ_HOLDING = 0x03
    MODBUS_FUNC_WRITE_SINGLE = 0x06

    def __init__(self, port: str, address: int = 1, timeout: float = -1) -> None:
        self.address = int(address)
        self.tempbox_port = get_tempbox_port(port)
        self.timeout = timeout if timeout > 0 else self.TEMPBOX_TIMEOUT
        self.serial_port = serial.Serial(
            port=self.tempbox_port,
            baudrate=self.TEMPBOX_BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            xonxoff=False,
            rtscts=False,
        )

    def close(self) -> None:
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

    def write_single_register(self, register: str, value: int) -> None:
        reg_addr = _d_register_to_addr(register)
        payload = reg_addr.to_bytes(2, byteorder='big') + int(value).to_bytes(2, byteorder='big', signed=False)
        request = _build_request(self.address, self.MODBUS_FUNC_WRITE_SINGLE, payload)
        self.serial_port.reset_input_buffer()
        self.serial_port.write(request)
        response = self.serial_port.read(8)
        if len(response) != 8 or response[:6] != request[:6]:
            raise RuntimeError(f'Write register failed: {register}, resp={response.hex()}')

    def read_holding_registers(self, register: str, quantity: int = 1) -> t.List[int]:
        reg_addr = _d_register_to_addr(register)
        payload = reg_addr.to_bytes(2, byteorder='big') + int(quantity).to_bytes(2, byteorder='big')
        request = _build_request(self.address, self.MODBUS_FUNC_READ_HOLDING, payload)
        expected_len = 5 + quantity * 2
        self.serial_port.reset_input_buffer()
        self.serial_port.write(request)
        response = self.serial_port.read(expected_len)
        if len(response) != expected_len:
            raise RuntimeError(f'Read register timeout: {register}, resp={response.hex()}')
        if response[0] != self.address or response[1] != self.MODBUS_FUNC_READ_HOLDING or response[2] != quantity * 2:
            raise RuntimeError(f'Invalid response frame: {response.hex()}')
        crc = _modbus_crc(response[:-2]).to_bytes(2, byteorder='little')
        if response[-2:] != crc:
            raise RuntimeError(f'Response CRC error: {response.hex()}')
        values = []
        for i in range(quantity):
            start = 3 + i * 2
            values.append(int.from_bytes(response[start : start + 2], byteorder='big'))
        return values

    def start_program_test(self, program_no: int) -> None:
        # D0090: 运行方式(0=程式), D0062: 程式号, D0063: 运行状态(0=停止, 1=运行)
        self.write_single_register('D0090', 0)
        self.write_single_register('D0062', int(program_no))
        self.write_single_register('D0063', 1)

    def start_custom_test(self, target_temp: float) -> None:
        target_raw = int(round(float(target_temp) * 10))
        if target_raw < 0:
            target_raw = (1 << 16) + target_raw
        self.write_single_register('D0090', 1)
        self.write_single_register('D0060', target_raw)
        self.write_single_register('D0063', 1)

    def stop_current_job(self) -> None:
        """Stop the running program test or custom fixed-value test."""
        self.write_single_register('D0063', 0)

    def read_realtime(self) -> t.Dict[str, t.Union[int, float]]:
        # D0063: 与 write 运行命令一致，程式正常结束后多为 0
        curr_temp_raw = self.read_holding_registers('D0010', 1)[0]
        set_temp_raw = self.read_holding_registers('D0011', 1)[0]
        running_prog = self.read_holding_registers('D0035', 1)[0]
        running_seg = self.read_holding_registers('D0036', 1)[0]
        running_state = self.read_holding_registers('D0031', 1)[0]
        run_cmd = self.read_holding_registers('D0063', 1)[0]
        return {
            'curr_temp': _to_signed_16(curr_temp_raw) / 10,
            'set_temp': _to_signed_16(set_temp_raw) / 10,
            'running_prog': running_prog,
            'running_seg': running_seg,
            'running_state': running_state,
            'run_cmd': run_cmd,
        }
