from .dut_base import DutBase
from .esp_mixin import EspMixin
from .mac_mixin import MacMixin


class DefaultMixins(MacMixin, EspMixin):
    pass


class EspDut(DefaultMixins, DutBase):
    pass
