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
                    print(f"Process '{self.process_name}' is not running. Resetting note_state.")
                    self.midi_monitor.reset_note_state()
                    self.midi_monitor.reset_note_buffer()
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
        self.note_state = {}  # Dictionary to store note intensity values
        self.note_buffer = {}  # Dictionary buffer for note proxy

    def stop(self):
        self._stop_event.set()

    def reset_note_state(self):
        self.note_state = {}  # Reset note state dictionary

    def reset_note_buffer(self):
        self.note_buffer = {}  # Reset note buffer

    def send_note_on(self, note, channel, velocity=1):
        with mido.open_output(self.output_device_name) as port:
            port.send(mido.Message('note_on', note=note, velocity=velocity, channel=channel))

    def add_note_buffer(self, note, channel, velocity=1):
        note_key = (note, channel)
        self.note_buffer[note_key] = velocity

    def remove_note_buffer(self, note, channel):
        note_key = (note, channel)
        self.note_buffer.pop(note_key)

    def send_note_buffer(self):
        for key in list(self.note_buffer.keys()):
            self.send_note_on(key[0], key[1], self.note_buffer[key])
        self.reset_note_buffer()

    def buffer_thread_func(self):
        try:
            while not self._stop_event.is_set():
                if len(self.midi_monitor.note_buffer) > 0:
                    time.sleep(0.1)  # Check every 0.1 seconds
                    self.midi_monitor.send_note_buffer()
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
                            self.note_state[(message.note, message.channel)] = True
                        elif message.velocity == 0:
                            self.note_state[(message.note, message.channel)] = False

                        print("loopback", message)
                        print("loopback", self.note_state)

                    if self._stop_event.is_set():
                        break
        except KeyboardInterrupt:
            pass

    def receiver_thread_func(self):
        try:
            with mido.open_input(self.input_device_name) as port:
                print(f"Monitoring MIDI input messages from {self.input_device_name}. Press Ctrl+C to exit.")
                for message in port:
                    self.handle_midi_message(message)
                    if self._stop_event.is_set():
                        break
        except KeyboardInterrupt:
            pass

    def handle_midi_message(self, message):

        note_channel = (message.note, message.channel)

        if message.type == 'note_on':
            # Velocity 127 is special handling code for only turning buttons on if they're off
            if message.velocity == 127:
                # Check if we know the current state of the note
                if note_channel in self.note_state:
                    # Only react to notes that have been turned off
                    if not self.note_state[note_channel]:
                        self.add_note_buffer(message.note, message.channel)  # Toggle the note on when buffer is ran
                else:
                    # Since we don't know the state, assume it is off so we want to turn it on
                    self.add_note_buffer(message.note, message.channel)  # Toggle the note on when buffer is ran
            else:
                # If we're not using the special velocity code, just pass the message along
                self.add_note_buffer(message.note, message.channel, message.velocity)

        elif message.type == 'note_off':
            # Note 127 is special handling code to turn off any active buttons
            # These commands are passed immediately, buffer runs after
            if message.note == 127:
                # Iterate over all known notes we have state for
                for key in list(self.note_state.keys()):
                    if self.note_state[key] is True:  # Only turn off notes that are on
                        self.send_note_on(key[0], key[1])  # Toggle the note off immediately
            else:
                # Check if we know the current state of the note
                if note_channel in self.note_state:
                    # Only react to notes that are on
                    if self.note_state[note_channel] is True:
                        self.send_note_on(message.note, message.channel)  # Toggle the note off immediately

        # Print the MIDI message
        print(message)
        print(self.note_state)

    def run(self):
        process_monitor = ProcessMonitor(self.process_name, self)
        process_monitor.start()

        # This thread processes the receiver (ProPresenter) msgs and replays them to the output device
        receiver_thread = threading.Thread(target=self.receiver_thread_func)
        receiver_thread.start()

        # This thread processes the buffer
        buffer_thread = threading.Thread(target=self.buffer_thread_func)
        buffer_thread.start()

        # This thread recieves msgs from ShowXpress which signal the button states
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
            receiver_thread.join()
            loopback_thread.join()

def stop():
    os._exit(1)

def main():
    # Replace 'Your MIDI Device Name' with the name of your MIDI device
    # You can find the device name by printing the available ports
    # Example: print(mido.get_input_names())
    print(mido.get_input_names())
    print(mido.get_output_names())

    # Hardware is setup as the following:
    # ProPresenter into USB MIDI Interface 2 (Input)
    # USB MIDI Interface 2 recieves PP MIDI msgs and determines if we need to pass that message a long
    # to the USB MIDI Interface 3 (Output) which is physically connected to the Steinberg UR22mkII
    # which is what's actually being used to toggle buttons in ShowXpress
    # and the loopMIDI Port 1 is recieving msgs from ShowXpress as buttons are toggled on/off and is
    # the primary method of state management

    # New design is setup as the following:
    #   ShowXpress listens to USB MIDI Interface 3 only
    #   ShowXpress sends button state over loopMIDI Port 1
    # The new hardware setup is the following:
    #   PP into Steinberg UR22mkII
    #   USB MIDI Interface has nothing plugged into it (or do we send from Steinberg UR22mkII?)

    # PP sends MIDI int Steinberg which is processed by the MIDI Tracker, state is taken into account
    # and any non specialized commands are pushed onto a buffer that is processed AFTER the special commands


    ## PP -> USB MIDI input -> USB MIDI output -> Steinberg UR22mkII input
    ## Virtual loopback input

    input_device_name = "Steinberg UR22mkII" # PP Receiver (input)
    output_device_name = "USB MIDI Interface 3" # Sender to ShowXpress MIDI (output)
    loopback_device_name = "loopMIDI Port 1" # State tracking (input)

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