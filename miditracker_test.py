import logging
import logging.handlers
import mido
import threading
import pathlib
import psutil
import sys
import os
import time
from queue import Queue
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)
launch_time = time.time()

LOG_DIRECTORY = pathlib.Path(__file__).parent.resolve().absolute()
WRITE_TO_MIDI = False

@dataclass
class StateChange:
    channel: int
    note: int
    value: bool
    timestamp: float

class ProcessMonitor(threading.Thread):
    def __init__(self, process_name, midi_monitor):
        super().__init__()
        self.process_name = process_name
        self.midi_monitor = midi_monitor
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            while not self._stop_event.is_set():
                if not self.check_process():
                    print(f"Process '{self.process_name}' is not running. Resetting state.")
                    self.midi_monitor.reset_state()
                time.sleep(5)
        except KeyboardInterrupt:
            pass

    def check_process(self):
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] == self.process_name:
                return True
        return False

class MidiMonitor(threading.Thread):
    def __init__(self, hardware_device_name, state_device_name, software_device_name, process_name):
        super().__init__()
        self.hardware_device_name = hardware_device_name
        self.state_device_name = state_device_name
        self.software_device_name = software_device_name
        self.process_name = process_name
        
        # Thread-safe queues for message passing
        self.state_queue = Queue()
        self.hardware_queue = Queue()
        self.output_queue = Queue()
        
        # Thread synchronization
        self._stop_event = threading.Event()
        self.state_lock = threading.Lock()
        
        # State management
        self.current_state: Dict[Tuple[int, int], bool] = {}
        self.pending_changes: Dict[Tuple[int, int], StateChange] = {}
        
        # Device initialization
        self.hardware_device = mido.open_input(self.hardware_device_name)
        self.state_device = mido.open_input(self.state_device_name)
        self.software_device = mido.open_output(self.software_device_name)

    def stop(self):
        self._stop_event.set()
        self.hardware_device.close()
        self.state_device.close()
        self.software_device.close()

    def reset_state(self):
        with self.state_lock:
            self.current_state.clear()
            self.pending_changes.clear()

    def process_hardware_message(self, msg: mido.Message) -> Optional[StateChange]:
        channel = getattr(msg, 'channel', 0)
        logger.info(f'Hardware CH:{channel} Note:{msg.note} Vel:{msg.velocity}')

        if msg.type == "note_on" and msg.velocity == 127:
            # Special code to turn on button
            return StateChange(channel, msg.note, True, time.time())
        elif msg.type == "note_off":
            if msg.note == 127:
                # Special code to clear all buttons
                with self.state_lock:
                    for key in self.current_state.keys():
                        self.output_queue.put(
                            StateChange(key[0], key[1], False, time.time())
                        )
                return None
            else:
                # Turn off specific button
                return StateChange(channel, msg.note, False, time.time())
        elif msg.type == "note_on":
            # Toggle button state
            current_state = False
            with self.state_lock:
                current_state = self.current_state.get((channel, msg.note), False)
            return StateChange(channel, msg.note, not current_state, time.time())
        
        return None

    def process_state_message(self, msg: mido.Message):
        channel = getattr(msg, 'channel', 0)
        if msg.type == "note_on":
            with self.state_lock:
                self.current_state[(channel, msg.note)] = msg.velocity > 0
                # Clean up any pending changes for this note
                self.pending_changes.pop((channel, msg.note), None)

    def hardware_thread_func(self):
        try:
            for msg in self.hardware_device:
                if self._stop_event.is_set():
                    break
                
                state_change = self.process_hardware_message(msg)
                if state_change:
                    self.output_queue.put(state_change)
                
                if WRITE_TO_MIDI:
                    self.software_device.send(msg)
        except KeyboardInterrupt:
            pass

    def state_thread_func(self):
        try:
            for msg in self.state_device:
                if self._stop_event.is_set():
                    break
                
                channel = getattr(msg, 'channel', 0)
                logger.info(f'State CH:{channel} Note:{msg.note} Vel:{msg.velocity}')
                self.process_state_message(msg)
        except KeyboardInterrupt:
            pass

    def output_thread_func(self):
        try:
            while not self._stop_event.is_set():
                try:
                    state_change = self.output_queue.get(timeout=0.1)
                    current_time = time.time()
                    
                    # Only process if enough time has passed since the last change
                    key = (state_change.channel, state_change.note)
                    
                    with self.state_lock:
                        pending = self.pending_changes.get(key)
                        current_state = self.current_state.get(key, False)
                        
                        if (not pending or 
                            current_time - pending.timestamp >= 0.1) and \
                            current_state != state_change.value:
                            
                            # Send MIDI message
                            msg = mido.Message(
                                "note_on",
                                channel=state_change.channel,
                                note=state_change.note,
                                velocity=1 if state_change.value else 0
                            )
                            if WRITE_TO_MIDI:
                                self.software_device.send(msg)
                            print(f"Sending: {msg}")
                            
                            # Update pending changes
                            self.pending_changes[key] = state_change
                            
                except Queue.Empty:
                    continue
        except KeyboardInterrupt:
            pass

    def run(self):
        process_monitor = ProcessMonitor(self.process_name, self)
        threads = [
            (process_monitor, "Process Monitor"),
            (threading.Thread(target=self.hardware_thread_func), "Hardware Thread"),
            (threading.Thread(target=self.state_thread_func), "State Thread"),
            (threading.Thread(target=self.output_thread_func), "Output Thread")
        ]
        
        # Start all threads
        for thread, name in threads:
            thread.start()
            print(f"Started {name}")

        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_event.set()
            for thread, name in threads:
                print(f"Stopping {name}")
                if isinstance(thread, ProcessMonitor):
                    thread.stop()
                thread.join(timeout=1)
                if thread.is_alive():
                    print(f"{name} failed to terminate properly")

class UnixTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return str(record.created - launch_time)

def main():
    LOG_FILE = str(LOG_DIRECTORY) + '\midi.log'
    print("Logging file:", LOG_FILE)
    handler = logging.handlers.TimedRotatingFileHandler(LOG_FILE, when='midnight', backupCount=12)
    formatter = UnixTimeFormatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    # Replace 'Your MIDI Device Name' with the name of your MIDI device
    # You can find the device name by printing the available ports
    # Example: print(mido.get_input_names())
    print("MIDI Inputs:", mido.get_input_names())
    print("MIDI Outputs:", mido.get_output_names())

    hardware_device_name = 'Steinberg UR22mkII -1 0' # Input from controller, gets put into queue and passed on
    state_device_name = 'loopMIDI Port 1' # DMX software is outputting button state to this
    software_device_name = 'showXPress 3' # DMX software is using this as the input
    
    process_name = "TheLightingController.exe"

    midi_monitor = MidiMonitor(hardware_device_name, state_device_name, software_device_name, process_name)
    midi_monitor.start()

    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("\nStopping MIDI monitoring...")

        midi_monitor.stop()
         # Wait for threads to terminate with a timeout
        midi_monitor.join(timeout=1)  # Timeout set to 1 seconds
        if midi_monitor.is_alive():
            print("Threads failed to terminate. Exiting without clean shutdown.", file=sys.stderr)
            os._exit(1) # Exit with an error code if threads fail to terminate within the timeout

if __name__ == "__main__":
    main()