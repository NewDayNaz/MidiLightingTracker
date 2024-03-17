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
                    print(f"Process '{self.process_name}' is not running. Resetting note_intensity.")
                    self.midi_monitor.reset_note_intensity()
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
    def __init__(self, input_device_name, output_device_name, loopback_device_name, process_name):
        super().__init__()
        self.input_device_name = input_device_name
        self.output_device_name = output_device_name
        self.loopback_device_name = loopback_device_name
        self.process_name = process_name
        self._stop_event = threading.Event()
        self.note_intensity = {}  # Dictionary to store note intensity values

    def stop(self):
        self._stop_event.set()

    def reset_note_intensity(self):
        self.note_intensity = {}  # Reset note intensity dictionary

    def send_note_on(self, note, channel, velocity=1):
        with mido.open_output(self.output_device_name) as port: # TODO: figure out how to do a loopback input
            port.send(mido.Message('note_on', note=note, velocity=velocity, channel=channel))

    def input_thread_func(self):
        try:
            with mido.open_input(self.input_device_name) as port:
                print(f"Monitoring MIDI input messages from {self.input_device_name}. Press Ctrl+C to exit.")
                for message in port:
                    self.handle_midi_message(message)
                    if self._stop_event.is_set():
                        break
        except KeyboardInterrupt:
            pass

    def loopback_thread_func(self):
        try:
            with mido.open_input(self.loopback_device_name) as port:
                print(f"Monitoring MIDI input messages from {self.loopback_device_name}. Press Ctrl+C to exit.")
                for message in port:
                    if message.type == 'note_on':
                        # Update note intensity value
                        if message.velocity > 0:
                            self.note_intensity[(message.note, message.channel)] = True
                        elif message.velocity == 0:
                            self.note_intensity[(message.note, message.channel)] = False

                        print("loopback", message)
                        print("loopback", self.note_intensity)
                    
                    if self._stop_event.is_set():
                        break
        except KeyboardInterrupt:
            pass

    def handle_midi_message(self, message):
        # TODO: figure out how to have a note_on msg that only turns something on
        if message.type == 'note_on':
            if message.velocity == 127:
                note_channel = (message.note, message.channel)
                time.sleep(0.05)
                if note_channel in self.note_intensity and not self.note_intensity[note_channel]:
                    self.send_note_on(message.note, message.channel) #toggle it back on
        if message.type == 'note_off':
            if message.note == 127:
                for key in list(self.note_intensity.keys()):
                    if self.note_intensity[key] is True:
                        self.send_note_on(key[0], key[1])
            else:
                # Remove note intensity value upon note off event
                note_channel = (message.note, message.channel)
                if note_channel in self.note_intensity and self.note_intensity[note_channel]:
                    self.send_note_on(message.note, message.channel)

        # Print the MIDI message
        print(message)
        print(self.note_intensity)

    def run(self):
        process_monitor = ProcessMonitor(self.process_name, self)
        process_monitor.start()

        input_thread = threading.Thread(target=self.input_thread_func)
        input_thread.start()

        loopback_thread = threading.Thread(target=self.loopback_thread_func)
        loopback_thread.start()

        try:
            while not self._stop_event.is_set():
                time.sleep(1)  # Adjust as needed
        except KeyboardInterrupt:
            pass
        finally:
            process_monitor.stop()
            process_monitor.join()
            input_thread.join()
            loopback_thread.join()

def stop():
    os._exit(1)

def main():
    # Replace 'Your MIDI Device Name' with the name of your MIDI device
    # You can find the device name by printing the available ports
    # Example: print(mido.get_input_names())
    print(mido.get_input_names())
    print(mido.get_output_names())
    input_device_name = 'Steinberg UR22mkII -1 0'
    loopback_device_name = 'loopMIDI Port 1'
    output_device_name = 'USB MIDI Interface 3'
    process_name = "TheLightingController.exe"

    midi_monitor = MidiMonitor(input_device_name, output_device_name, loopback_device_name, process_name)
    midi_monitor.start()

    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("\nStopping MIDI monitoring...")

        midi_monitor.stop()
         # Wait for threads to terminate with a timeout
        midi_monitor.join(timeout=3)  # Timeout set to 3 seconds
        if midi_monitor.is_alive():
            print("Threads failed to terminate. Exiting without clean shutdown.", file=sys.stderr)
            os._exit(1) # Exit with an error code if threads fail to terminate within the timeout

if __name__ == "__main__":
    main()