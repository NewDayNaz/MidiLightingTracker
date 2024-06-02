import logging
import mido
import threading
import psutil
import sys
import os
import time

logger = logging.getLogger(__name__)
launch_time = time.time()

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
                time.sleep(5)  # Check every 5 seconds
        except KeyboardInterrupt:
            pass

    def check_process(self):
        # Check if the process is running
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

        self.hardware_device = mido.open_input(self.hardware_device_name)
        self.state_device = mido.open_input(self.state_device_name)
        self.software_device = mido.open_output(self.software_device_name)

        self.process_name = process_name
        self._stop_event = threading.Event()
        self.state = {}  # Dictionary to store note intensity values
        self.desired_state = {}
        self.desired_clear_state = {}

        self.write_lock = threading.Lock()
        self.write_time = time.time()

    def stop(self):
        self.hardware_device.close()
        self.state_device.close()
        self.software_device.close()
        self._stop_event.set()

    def desire_state_toggle(self, value):
        self.write_time = time.time()

        msg_channel = 0
        if hasattr(value, "channel"):
            msg_channel = value.channel

        key = (msg_channel, value.note)
        has_key = key in self.state
        if (not has_key) or (has_key and (not self.state[key])):
            self.desired_state[key] = True
        elif has_key and self.state[key]:
            self.desired_state[key] = False

    def desire_state_on(self, value):
        self.write_time = time.time()
        key = (value.channel, value.note)
        self.desired_state[key] = True

    def desire_state_off(self, value):
        self.write_time = time.time()
        key = (value.channel, value.note)
        self.desired_state[key] = False

    def desire_state_cleared(self, value):
        self.write_time = time.time()
        key = (value.channel, value.note)
        has_desired_state = key in self.desired_clear_state
        if not has_desired_state: # only enforce state if no one has requested one yet
            self.desired_clear_state[key] = False
    
    def flush_queue(self):
        self.write_time = time.time()
        self.desired_state = {}
        self.desired_clear_state = {}

    # only allow pushing to the queue if nothing has written to it in 100ms
    def can_push_queue(self, write_time):
        return (time.time() - write_time) > 0.1

    def update_state(self, msg):
        msg_channel = 0
        if hasattr(msg, "channel"):
            msg_channel = msg.channel

        if msg.type == "note_on":
            # Update note intensity value
            if msg.velocity > 0:
                self.state[(msg_channel, msg.note)] = True
            elif msg.velocity == 0:
                self.state[(msg_channel, msg.note)] = False

    def reset_state(self):
        self.state = {}  # Reset note state dictionary

    def process_hardware_msg(self, msg):
        handled = False
        msg_channel = 0
        if hasattr(msg, "channel"):
            msg_channel = msg.channel

        logger.info('{0} CH:{1} Note:{2} Vel:{3}'.format(msg.type, msg.channel, msg.note, msg.velocity))

        if msg.type == "note_on":
            if msg.velocity == 127: # special code, only turns on button
                handled = True
                print("Turn On:", msg)
                self.desire_state_on(
                    mido.Message("note_on", channel=msg_channel, note=msg.note, velocity=1)
                )
        if msg.type == "note_off":
            handled = True
            if msg.note == 127: # special code, clear all active buttons
                print("Clear All:", msg)
                for key in list(self.state.keys()):
                    self.desire_state_cleared(
                        mido.Message("note_on", channel=key[0], note=key[1], velocity=1)
                    )
            else:
                # All note_off events, only turns off button
                print("Turn Off:", msg)
                self.desire_state_off(
                    mido.Message("note_on", channel=msg_channel, note=msg.note, velocity=1)
                )

        # process unhandled regular messages
        if (not handled):
            msg = mido.Message("note_on", channel=msg_channel, note=msg.note, velocity=1)
            self.software_device.send(msg)
            print("Toggle:", msg)
            # self.desire_state_toggle(msg)

    def hardware_thread_func(self):
        try:
            for msg in self.hardware_device:
                print("Hardware:", msg)
                
                # make sure queue doesn't get pushed
                self.write_lock.acquire()
                self.process_hardware_msg(msg)
                self.write_lock.release()

                if self._stop_event.is_set():
                    break
        except KeyboardInterrupt:
            pass

    def state_thread_func(self):
        try:
            for msg in self.state_device:
                # print("State: ", msg)

                # make sure queue doesn't get pushed
                self.write_lock.acquire()
                self.write_time = time.time() + 0.005 # delay queue push by 5ms more after state change
                self.update_state(msg)
                self.write_lock.release()

                if self._stop_event.is_set():
                    break
        except KeyboardInterrupt:
            pass

    def software_thread_func(self):
        try:
            while not self._stop_event.is_set():
                time.sleep(0.005) # only check queue every 5ms
                can_push_queue = self.can_push_queue(self.write_time)
                if can_push_queue:
                    desired_state_len = len(self.desired_state)
                    desired_clear_state_len = len(self.desired_clear_state)
                    if desired_state_len > 0 or desired_clear_state_len > 0:
                        print("Pre State:", self.state)
                        print("Pre Desired:", self.desired_state)
                        print("Clear Desired:", self.desired_clear_state)

                    for key in list(self.desired_clear_state.keys()):
                        if not (key in self.desired_state): # only clear state if no pre-existing intent
                            self.desired_state[key] = False

                    if desired_state_len > 0 or desired_clear_state_len > 0:
                        print("Post Desired:", self.desired_state)

                    for key in list(self.desired_state.keys()):
                        state_desire = self.desired_state[key]
                        state_current = False
                        if key in self.state:
                            state_current = self.state[key]

                        if state_current != state_desire:
                            msg = mido.Message("note_on", channel=key[0], note=key[1], velocity=1)
                            self.software_device.send(msg)
                            print("Toggle:", msg)

                    # flush queues
                    if desired_state_len > 0 or desired_clear_state_len > 0:
                        print("Post State:", self.state)
                        self.write_lock.acquire()
                        self.write_time = time.time()
                        self.flush_queue()
                        self.write_lock.release()
        except KeyboardInterrupt:
            pass

    def run(self):
        process_monitor = ProcessMonitor(self.process_name, self)
        process_monitor.start()

        hardware_thread = threading.Thread(target=self.hardware_thread_func)
        hardware_thread.start()

        state_thread = threading.Thread(target=self.state_thread_func)
        state_thread.start()

        software_thread = threading.Thread(target=self.software_thread_func)
        software_thread.start()

        try:
            while not self._stop_event.is_set():
                time.sleep(1)  # Adjust as needed
        except KeyboardInterrupt:
            pass
        finally:
            process_monitor.stop()
            process_monitor.join()
            hardware_thread.join()
            state_thread.join()
            software_thread.join()

def stop():
    os._exit(1)

class UnixTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return str(int(record.created) - int(launch_time))

def main():
    handler = logging.StreamHandler()
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