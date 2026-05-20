import json
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from .exceptions import SnifferConnectionError, SnifferError, SnifferRecordingError


def _default_btacli_path() -> str:
    """Resolve bundled ``btacli`` under ``esptest/bta_remote_api`` (linux-x64)."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    esptest_root = os.path.dirname(pkg_dir)
    return os.path.join(
        esptest_root, 'bta_remote_api', 'Binaries', 'btacli', 'linux-x64', 'btacli'
    )


class SnifferClient:
    """Python client for the Ellisys Bluetooth Analyzer remote control.

    Connects to an Ellisys analyzer application via the btacli CLI tool.

    Usage::

        client = SnifferClient(host="192.168.1.100", port=12345)

        # Context manager (recommended for test cases)
        with client.recording("my_test_case"):
            run_test()
        # Saves as my_test_case_20260511.btt, aborts on exception

        # Explicit control
        client.start_recording()
        client.stop_recording("/path/to/trace.btt")
    """

    def __init__(
        self, host: str = "localhost", port: int = 12345, btacli_path: Optional[str] = None
    ):
        self._host = host
        self._port = port
        self._btacli_path = btacli_path or _default_btacli_path()

        if not os.path.isfile(self._btacli_path):
            raise SnifferError(f"btacli binary not found: {self._btacli_path}")

        if not os.access(self._btacli_path, os.X_OK):
            raise SnifferError(f"btacli binary is not executable: {self._btacli_path}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _base_cmd(self) -> list:
        return [self._btacli_path, "-a", self._host, "-p", str(self._port)]

    def _run(self, args: list, parse_json: bool = False) -> str:
        """Run a btacli command and return stdout. Raises SnifferError on failure."""
        cmd = self._base_cmd() + args
        if parse_json:
            cmd += ["--format", "Json"]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            raise SnifferError(f"btacli command timed out: {' '.join(args)}")
        except FileNotFoundError:
            raise SnifferError(f"btacli binary not found at {self._btacli_path}")

        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise SnifferError(msg)

        output = result.stdout.strip()
        if parse_json and output:
            try:
                parsed = json.loads(output)
                return parsed
            except json.JSONDecodeError:
                pass
        return output

    # ------------------------------------------------------------------
    # Analyzer management
    # ------------------------------------------------------------------

    def list_analyzers(self):
        """List available analyzer IDs. Returns a parsed JSON value."""
        return self._run(["recording", "list"], parse_json=True)

    def select_analyzer(self, analyzer_id: str):
        """Select the analyzer to record from (by serial number, e.g. BV1-12345)."""
        self._run(["recording", "select", analyzer_id])

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start_recording(self):
        """Start recording on the selected analyzer."""
        self._run(["recording", "start"])

    def stop_recording(self, filepath: str, overwrite: bool = True) -> str:
        """Stop recording and save the trace to *filepath* on the server side.

        Returns *filepath* on success.
        """
        args = ["recording", "stop-save", filepath]
        if overwrite:
            args.append("--overwrite")
        self._run(args)
        return filepath

    def abort_recording(self):
        """Abort the current recording and discard the trace data."""
        self._run(["recording", "abort"])

    def is_recording(self) -> bool:
        """Return True if the analyzer is currently recording."""
        status = self.status()
        if isinstance(status, dict):
            return bool(status)
        return False

    def status(self):
        """Return the current recording status as a parsed JSON value.

        Keys may include DataSource, DurationSeconds, FileSize.
        """
        return self._run(["recording", "status"], parse_json=True)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    @contextmanager
    def recording(self, filename_prefix: str, output_dir: str = "."):
        """Context manager that starts recording, yields, then stops and saves.

        On successful exit the trace is saved as
        ``{output_dir}/{filename_prefix}_{YYYYMMDD}.btt``.
        If an exception occurs inside the block the recording is aborted.

        Usage::

            with client.recording("my_test", "/tmp/traces"):
                run_test()
        """
        started = False
        try:
            self.start_recording()
            started = True
            yield
        except Exception:
            if started:
                try:
                    self.abort_recording()
                except SnifferError:
                    pass
            raise
        else:
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"{filename_prefix}_{date_str}.btt"
            filepath = os.path.join(output_dir, filename)
            self.stop_recording(filepath)
