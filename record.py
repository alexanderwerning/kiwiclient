import os
import time
import math
import numpy as np
from kiwiclient.kiwirecorder import KiwiSoundRecorder
from kiwiclient.kiwi.client import KiwiTooBusyError, KiwiTimeLimitError, KiwiServerTerminatedConnection
from threading import Thread, Event, Lock, Semaphore
from typing import Optional, Callable


class KiwiRecorder(KiwiSoundRecorder):
    def __init__(self, options):
        super(KiwiRecorder, self).__init__(options)
        self.data = np.array([])
        self.position = None

    def _on_gnss_position(self, pos):
        self.position = pos

    def _write_samples(self, samples, *args):
        self.data = np.append(self.data, samples)


class KiwiOptions:
    def __init__(self, **kwargs):
        options = {"server_host": "localhost",
                   "server_port": 8073,
                   "user": "kiwirecorder.py",
                   "password": "",
                   "tlimit_password": "",
                   "tlimit": 10,
                   "launch_delay": 0,
                   "connect_retries": 0,
                   "connect_timeout": 15,
                   "socket_timeout": 10,
                   "no_api": False,
                   "frequency": 1000,
                   "modulation": "am",
                   "compression": True,
                   "lp_cut": None,
                   "hp_cut": None,
                   "resample": 0,
                   "sq_thresh": None,
                   "squelch_tail": 1.0,
                   "agc_gain": None,
                   "nb": False,
                   "nb_gate": 100,
                   "nb_thresh": 50,
                   "sound": False,
                   "S_meter": -1,
                   "sdt": 0,
                   "zoom": 0,
                   "rigctl_enabled": False,
                   "is_kiwi_tdoa": False,
                   "timestamp": int(time.time() + os.getpid()) & 0xffffffff,
                   "idx": 0,
                   "agc_yaml_file": None,
                   "test_mode": False,
                   "ADC_OV": False,
                   "raw": False,
                   "quiet": False,
                   "thresh": None}
        if not all([key in options for key in kwargs.keys()]):
            raise ValueError("Unknown parameters")

        options.update(kwargs)
        for key, value in options.items():
            setattr(self, key, value)


class RingBuffer():
    """Controls communication between receiving and processing thread.

    It is assumed that only one processing thread exists.
    """

    def __init__(self, size=12001):
        self.buffer = np.zeros(size)
        self.access = Lock()
        self.updated = Event()

    def read(self):
        self.updated.wait()
        self.updated.clear()
        with self.access:
            data = self.buffer.copy()
        return data

    def write(self, data):
        with self.access:
            data_size = len(data)
            buffer_size = len(self.buffer)
            if data_size >= buffer_size:
                self.buffer = data[data_size-buffer_size:]
            else:
                shift = data_size
                self.buffer[:buffer_size-shift] = self.buffer[shift:]
                self.buffer[buffer_size-shift:] = data
        self.updated.set()


def _record(buffer: Optional[RingBuffer] = None, stop_event=None, **kwargs):
    options = KiwiOptions(**kwargs)
    recorder = KiwiRecorder(options)
    recorder._reader = True
    connect_count = options.connect_retries
    while stop_event is None or not stop_event.is_set():  # run
        try:
            recorder.connect(options.server_host, options.server_port)
        except Exception as e:
            print(e)
            connect_count -= 1
            if options.connect_retries > 0 and connect_count == 0:
                break
            if options.connect_timeout > 0:
                time.sleep(options.connect_timeout)
            continue

        try:
            recorder.open()
            while stop_event is None or not stop_event.is_set():
                recorder.run()
                if options.tlimit is None and buffer is not None:
                    buffer.write(recorder.data)
                    recorder.data = np.array([])
                elif options.tlimit is not None and len(recorder.data) > 12001 * options.tlimit:
                    raise KiwiTimeLimitError('time limit reached')
        except KiwiServerTerminatedConnection as e:
            if options.no_api:
                msg = ''
            else:
                msg = ' Reconnecting after 5 seconds'
            recorder.close()
            if options.no_api:  # don't retry
                break
            recorder._start_ts = None  # this makes the recorder open a new file on restart
            time.sleep(5)
            continue
        except KiwiTooBusyError:
            time.sleep(15)
            continue
        except KiwiTimeLimitError:
            break

    recorder.close()
    if options.tlimit is not None:
        return recorder.data[:options.tlimit*12001]
    else:
        # return last received packet
        return recorder.data


def record_audio(**kwargs):
    return _record(**kwargs)


def stream_audio(process_data: Callable[[RingBuffer], None], buffer_size=12001, start_filled=True, **kwargs):
    if "tlimit" not in kwargs:
        kwargs["tlimit"] = None
    buffer = RingBuffer(size=12001)
    stop_event = Event()
    recording_thread = Thread(target=_record,
                              args=(buffer, stop_event),
                              kwargs=kwargs)

    fill_size = 2000  # number of samples returned by kiwi device

    try:
        recording_thread.start()
        if start_filled:
            # wait for buffer to fill
            for _ in range(math.ceil(buffer_size/fill_size)):
                buffer.read()

        process_data(buffer)

    except KeyboardInterrupt:
        print("Keyboard interrupt caught, exiting.")
    finally:
        stop_event.set()
        recording_thread.join()
