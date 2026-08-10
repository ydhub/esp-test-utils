import pytest

import esptest.common.compat_typing as t
from esptest.devices.multimeter.base import (
    DeviceInfo,
    MultimeterBackend,
    MultimeterError,
    get_backend_class,
    registered_backends,
)


def test_backend_auto_register() -> None:
    class DummyBackend(MultimeterBackend):
        backend_name = 'dummy_test_only'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return []

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    assert get_backend_class('dummy_test_only') is DummyBackend
    assert 'dummy_test_only' in registered_backends()
    # cleanup registry so other tests stay isolated
    registered_backends().pop('dummy_test_only', None)


def test_unknown_backend_keyerror() -> None:
    with pytest.raises(KeyError):
        get_backend_class('no_such_backend')


def test_device_info_fields() -> None:
    info = DeviceInfo(backend='gpib', address=22, resource=None, identity='IDN')
    assert info.backend == 'gpib'
    assert info.address == 22


def test_multimeter_error_is_oserror() -> None:
    assert issubclass(MultimeterError, OSError)


def test_list_multimeters_explicit_backend() -> None:
    from esptest.devices.multimeter.factory import list_multimeters

    class FakeListBackend(MultimeterBackend):
        backend_name = 'fake_list'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_list', address=filters.get('address'))]

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    try:
        infos = list_multimeters(backend='fake_list', address=7)
        assert len(infos) == 1
        assert infos[0].backend == 'fake_list'
        assert infos[0].address == 7
    finally:
        registered_backends().pop('fake_list', None)


def test_list_multimeters_ambiguous_requires_backend() -> None:
    from esptest.devices.multimeter.factory import list_multimeters

    class FakeA(MultimeterBackend):
        backend_name = 'fake_a'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_a')]

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    class FakeB(MultimeterBackend):
        backend_name = 'fake_b'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_b')]

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    try:
        with pytest.raises(RuntimeError, match='backend'):
            list_multimeters()
    finally:
        registered_backends().pop('fake_a', None)
        registered_backends().pop('fake_b', None)


def test_list_multimeters_skips_not_implemented_backend() -> None:
    from esptest.devices.multimeter.factory import list_multimeters

    class FakeSkip(MultimeterBackend):
        backend_name = 'fake_skip'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            raise NotImplementedError('unsupported filter')

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    class FakeWorks(MultimeterBackend):
        backend_name = 'fake_works'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_works', address=5)]

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    try:
        infos = list_multimeters(path='/dev/joulescope')
        assert len(infos) == 1
        assert infos[0].backend == 'fake_works'
        assert infos[0].address == 5
    finally:
        registered_backends().pop('fake_skip', None)
        registered_backends().pop('fake_works', None)


def test_list_multimeters_explicit_backend_not_implemented_propagates() -> None:
    from esptest.devices.multimeter.factory import list_multimeters

    class FakeNie(MultimeterBackend):
        backend_name = 'fake_nie'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            raise NotImplementedError('unsupported filter')

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    try:
        with pytest.raises(NotImplementedError, match='unsupported filter'):
            list_multimeters(backend='fake_nie', path='/dev/joulescope')
    finally:
        registered_backends().pop('fake_nie', None)


def test_get_multimeter_specific_one_match() -> None:
    from esptest.devices.multimeter.facade import Multimeter
    from esptest.devices.multimeter.factory import get_multimeter_specific

    class FakeOne(MultimeterBackend):
        backend_name = 'fake_one'

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_one', address=3, resource='R')]

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def prepare(self, sample_rate_s: float) -> None:
            pass

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    try:
        mm = get_multimeter_specific(backend='fake_one')
        assert isinstance(mm, Multimeter)
        assert mm.sample_rate is None
        assert mm._address == 3
        assert mm._resource == 'R'
    finally:
        registered_backends().pop('fake_one', None)
