import mido
import threading
import psutil
import sys
import os
import time

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

        self.write_lock = threading.Lock()
        self.write_time = time.time()
        self.prio_queue = []
        self.queue = []

    def stop(self):
        self.hardware_device.close()
        self.state_device.close()
        self.software_device.close()
        self._stop_event.set()

    def write_prio_queue(self, value):
        self.write_time = time.time()
        self.prio_queue.append(value)

    def write_queue(self, value):
        self.write_time = time.time()
        self.queue.append(value)
    
    def flush_queue(self):
        self.write_time = time.time()
        self.prio_queue = []
        self.queue = []

    # only allow pushing to the queue if nothing has written to it in 50ms
    def can_push_queue(self, write_time):
        return (time.time() - write_time) > 0.05

    def update_state(self, msg):
        if msg.type == 'note_on':
            # Update note intensity value
            if msg.velocity > 0:
                self.state[(msg.channel, msg.note)] = True
            elif msg.velocity == 0:
                self.state[(msg.channel, msg.note)] = False

    def reset_state(self):
        self.state = {}  # Reset note state dictionary

    def process_hardware_msg(self, msg):
        self.software_device.send(msg)

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
                print("State: ", msg)

                # make sure queue doesn't get pushed
                self.write_lock.acquire()

                self.write_time = time.time()
                self.update_state(msg)

                self.write_lock.release()

                print(self.state)

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
                    prio_len = len(self.prio_queue)
                    queue_len = len(self.queue)
                    for pkt in self.prio_queue:
                        self.software_device.send(pkt)
                        print("Prio Q:", pkt)

                    if prio_len > 0 and queue_len > 0:
                        time.sleep(0.05) # allow prio pkts to get processed first, wait 50ms

                    for pkt in self.queue:
                        self.software_device.send(pkt)
                        print("Q:", pkt)

                    # flush queues
                    if prio_len > 0 or queue_len > 0:
                        self.write_lock.acquire()
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

def main():
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