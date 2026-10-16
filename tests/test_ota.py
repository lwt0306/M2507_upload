"""No hardware needed: serial protocol, cancellation, GUI/worker integration."""
import collections
import os
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import M2507_dual_core_ota_scrollable as ota


class BufferedSerial:
    is_open = True

    def __init__(self, *chunks):
        self.chunks = collections.deque(chunks)
        self.writes = []

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, size):
        data = self.chunks.popleft()
        if len(data) > size:
            self.chunks.appendleft(data[size:])
        return data[:size]

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.chunks.clear()

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False


class DeviceSerial(BufferedSerial):
    """Checks length/CRC and coalesces final ACKs like a fast device."""
    def __init__(self):
        super().__init__()
        self.payload = bytearray()
        self.info = None

    def reset_input_buffer(self):
        self.chunks.clear()
        self.chunks.append(ota.CMD_PROMPT_POWERON)

    def write(self, data):
        super().write(data)
        if self.info is None:
            assert data[:2] == ota.FRAME_HEADER and len(data) == 11
            self.info = struct.unpack('<BII', data[2:])
            self.chunks.append(ota.CMD_ACK_INFO_OK)
        else:
            self.payload.extend(data)
            _, length, crc = self.info
            assert len(self.payload) <= length
            if len(self.payload) == length:
                assert zlib.crc32(self.payload) & 0xffffffff == crc
                self.chunks.append(ota.CMD_ACK_CRC_OK + ota.CMD_ACK_FLASH_OK)
        return len(data)


class NoTkInWorker:
    def __getattr__(self, name):
        raise AssertionError('Worker accessed Tk: ' + name)


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        if threading.current_thread() is not threading.main_thread():
            raise AssertionError('Worker read a Tk variable')
        return self.value


class Control(dict):
    def config(self, **kwargs):
        self.update(kwargs)


def bare_app(serial=None):
    app = ota.DualCoreOtaUpgraderApp.__new__(ota.DualCoreOtaUpgraderApp)
    app.root = NoTkInWorker()
    app.ui_queue = queue.Queue()
    app.stop_event = threading.Event()
    app.is_upgrading = True
    app._closing = False
    app._rx_buffer = b''
    app.serial = serial if serial is not None else BufferedSerial()
    app.bin_data = bytes(range(256)) * 8 + b'end'
    app.file_size = len(app.bin_data)
    app.file_crc = zlib.crc32(app.bin_data) & 0xffffffff
    app.file_path = 'firmware.bin'
    app.active_target_core = ota.TARGET_CORE0
    app.active_chunk_size = 512
    app.chunk_size_var = Value('512')
    return app


class ProtocolTests(unittest.TestCase):
    def test_info_frame_both_cores(self):
        app = bare_app()
        for core in (ota.TARGET_CORE0, ota.TARGET_CORE1):
            app.active_target_core = core
            frame = app.make_info_frame()
            self.assertEqual(len(frame), 11)
            self.assertEqual(frame[:2], b'\xeb\x90')
            self.assertEqual(struct.unpack('<BII', frame[2:]), (core, app.file_size, app.file_crc))

    def test_fragmented_frame_with_noise(self):
        app = bare_app(BufferedSerial(b'noise\xeb', b'\x90\x88', b'\xdd\x88\xdd'))
        self.assertTrue(app.wait_for_response(ota.CMD_ACK_CRC_OK, .5, 'crc'))

    def test_coalesced_ack_preserved(self):
        app = bare_app(BufferedSerial(ota.CMD_ACK_CRC_OK + ota.CMD_ACK_FLASH_OK))
        app.wait_for_response(ota.CMD_ACK_CRC_OK, .5, 'crc')
        self.assertEqual(app._rx_buffer, ota.CMD_ACK_FLASH_OK)
        self.assertTrue(app.wait_for_response(ota.CMD_ACK_FLASH_OK, .5, 'flash'))

    def test_error_before_success_is_not_hidden(self):
        app = bare_app(BufferedSerial(ota.CMD_ACK_CRC_ERR + ota.CMD_ACK_CRC_OK))
        with self.assertRaisesRegex(Exception, 'CRC'):
            app.wait_for_response(ota.CMD_ACK_CRC_OK, .5, 'crc')

    def test_all_device_error_frames(self):
        for error in (ota.CMD_ACK_INFO_ERR, ota.CMD_ACK_CRC_ERR, ota.CMD_ACK_FLASH_ERR, ota.CMD_ACK_CORE_ERR):
            with self.subTest(error=error):
                app = bare_app(BufferedSerial(error))
                with self.assertRaisesRegex(Exception, '下位机返回'):
                    app.wait_for_response(ota.CMD_ACK_INFO_OK, .5, 'info')

    def test_timeout_uses_monotonic_clock(self):
        app = bare_app()
        with patch.object(ota.time, 'time', side_effect=AssertionError('wall clock used')):
            with self.assertRaisesRegex(Exception, '超时'):
                app.wait_for_response(ota.CMD_ACK_INFO_OK, .02, 'info')

    def test_cancellation_interrupts_wait(self):
        app = bare_app()
        app.stop_event.set()
        with self.assertRaisesRegex(Exception, '停止'):
            app.wait_for_response(ota.CMD_ACK_INFO_OK, 60, 'info')

    def test_short_write_is_rejected(self):
        app = bare_app()
        with patch.object(app.serial, 'write', return_value=1):
            with self.assertRaisesRegex(ota.serial.SerialTimeoutException, '发送不完整'):
                app._write_serial(b'abcd')

    def test_full_upgrade_on_worker_for_each_core_and_chunk_size(self):
        for core in (ota.TARGET_CORE0, ota.TARGET_CORE1):
            for chunk_size in (128, 512, 1024):
                with self.subTest(core=core, chunk_size=chunk_size):
                    device = DeviceSerial()
                    app = bare_app(device)
                    app.active_target_core = core
                    app.active_chunk_size = chunk_size
                    worker = threading.Thread(target=app.upgrade_task, daemon=True)
                    worker.start()
                    worker.join(3)
                    self.assertFalse(worker.is_alive(), 'worker timed out')
                    items = list(app.ui_queue.queue)
                    self.assertIn(('dialog', True, '固件升级并校验成功。'), items)
                    self.assertEqual(items[-1], ('finished',))
                    self.assertEqual(bytes(device.payload), app.bin_data)
                    self.assertEqual(device.info, (core, app.file_size, app.file_crc))

    def test_stop_does_not_enable_a_second_worker(self):
        app = bare_app()
        app.btn_stop = Control()
        app.stop_upgrade()
        self.assertTrue(app.is_upgrading)
        self.assertTrue(app.stop_event.is_set())
        self.assertEqual(app.btn_stop['state'], 'disabled')
        with patch.object(ota.threading, 'Thread') as thread:
            app.start_upgrade()
            thread.assert_not_called()

    def test_start_snapshots_chunk_size_and_locks_controls(self):
        app = bare_app(DeviceSerial())
        app.is_upgrading = False
        app.target_core_var = Value(ota.TARGET_CORE1)
        app.chunk_size_var = Value('128')
        for name in ('btn_start', 'btn_stop', 'btn_open', 'btn_select_file', 'rb_core0', 'rb_core1'):
            setattr(app, name, Control())
        with patch.object(ota.threading, 'Thread') as thread:
            app.start_upgrade()
            thread.return_value.start.assert_called_once()
        self.assertEqual(app.active_chunk_size, 128)
        self.assertEqual(app.active_target_core, ota.TARGET_CORE1)
        for name in ('btn_start', 'btn_open', 'btn_select_file', 'rb_core0', 'rb_core1'):
            self.assertEqual(getattr(app, name)['state'], 'disabled')

    def test_worker_reports_device_error_and_finishes(self):
        app = bare_app(BufferedSerial(ota.CMD_ACK_CORE_ERR))
        app.serial.reset_input_buffer = lambda: None
        app.upgrade_task()
        items = list(app.ui_queue.queue)
        self.assertEqual(items[-1], ('finished',))
        self.assertTrue(any(item[0] == 'dialog' and item[1] is False and '目标核' in item[2] for item in items))


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'GUI requires a display (Xvfb on Linux)')
class GuiTests(unittest.TestCase):
    def test_serial_enumeration_failure_keeps_the_gui_open(self):
        root = ota.tk.Tk()
        root.withdraw()
        try:
            with patch.object(ota.serial.tools.list_ports, 'comports', side_effect=OSError('driver failure sentinel')):
                app = ota.DualCoreOtaUpgraderApp(root)
            root.update_idletasks()
            app._process_ui_queue()
            self.assertTrue(root.winfo_exists())
            self.assertEqual(app.status_var.get(), '串口枚举失败，请检查驱动')
            self.assertIn('driver failure sentinel', app.txt_log.get('1.0', 'end'))
            self.assertEqual(str(app.btn_start['state']), 'disabled')
        finally:
            for callback in root.tk.call('after', 'info'):
                root.after_cancel(callback)
            root.destroy()

    def test_real_tk_load_connect_upgrade_and_close(self):
        root = ota.tk.Tk()
        root.withdraw()
        try:
            with patch.object(ota.serial.tools.list_ports, 'comports', return_value=[]):
                app = ota.DualCoreOtaUpgraderApp(root)
            self.assertEqual(root.title(), 'M2507双核串口固件升级工具')
            self.assertEqual(str(app.btn_start['state']), 'disabled')
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / '固件.bin'
                data = bytes(range(256)) * 3
                path.write_bytes(data)
                with patch.object(ota.filedialog, 'askopenfilename', return_value=str(path)):
                    app.select_file()
            app.port_var.set('TEST')
            device = DeviceSerial()
            with patch.object(ota.serial, 'Serial', return_value=device):
                app.toggle_serial()
            self.assertEqual(str(app.btn_start['state']), 'normal')
            app.start_upgrade()
            self.assertEqual(str(app.btn_select_file['state']), 'disabled')
            with patch.object(ota.messagebox, 'showinfo') as success, patch.object(ota.messagebox, 'showerror') as error:
                deadline = time.monotonic() + 3
                while app.is_upgrading and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.01)
                self.assertFalse(app.is_upgrading)
                success.assert_called_once()
                error.assert_not_called()
            self.assertEqual(bytes(device.payload), data)
            self.assertEqual(str(app.btn_start['state']), 'normal')
            self.assertEqual(str(app.rb_core0['state']), 'normal')
            self.assertEqual(app.status_var.get(), '升级成功')
            app.on_close()
            self.assertFalse(device.is_open)
            root = None
        finally:
            if root is not None:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
