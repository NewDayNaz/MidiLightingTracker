import threading
import time
import queue

class MidiStateHandler:
    def __init__(self):
        self.state = {}
        self.desired_state_queue = queue.Queue()  # Thread-safe queue for state changes
        self.lock = threading.Lock()
        self.hardware_msgs_queue = queue.Queue()  # Queue for hardware messages
        self.write_event = threading.Event()  # Event to notify software thread
        self.running = True

    def state_thread_func(self):
        """
        Thread to monitor and push updates to the desired state queue.
        """
        while self.running:
            with self.lock:
                current_state = self.state.copy()  # Copy to work on without holding lock
            # Push state changes to the desired_state_queue
            for key, value in current_state.items():
                self.desired_state_queue.put((key, value))  # Enqueue desired state changes

            time.sleep(0.1)  # Add delay to avoid excessive CPU usage

    def software_thread_func(self):
        """
        Thread to process the desired state queue and send MIDI messages.
        """
        while self.running:
            try:
                # Wait for a state change notification or timeout
                key, value = self.desired_state_queue.get(timeout=0.1)
                # Process the desired state update
                self.send_midi_message(key, value)
            except queue.Empty:
                pass  # Timeout, no state changes to process

    def hardware_thread_func(self):
        """
        Thread to monitor hardware messages and update the state.
        """
        while self.running:
            try:
                hardware_msg = self.hardware_msgs_queue.get(timeout=0.1)  # Simulate receiving a hardware message
                self.process_hardware_msg(hardware_msg)
            except queue.Empty:
                pass  # No messages received

    def process_hardware_msg(self, msg):
        """
        Process a message from hardware and update the state.
        """
        with self.lock:
            # Update the shared state based on hardware message
            self.state[msg['key']] = msg['value']
            # Notify the software thread about state changes
            self.desired_state_queue.put((msg['key'], msg['value']))
            self.write_event.set()

    def send_midi_message(self, key, value):
        """
        Simulate sending a MIDI message.
        """
        print(f"Sending MIDI message: {key} -> {value}")

    def stop(self):
        """
        Stop all threads.
        """
        self.running = False
        self.write_event.set()  # Wake up any waiting threads


# Example of usage
midi_handler = MidiStateHandler()

state_thread = threading.Thread(target=midi_handler.state_thread_func, daemon=True)
software_thread = threading.Thread(target=midi_handler.software_thread_func, daemon=True)
hardware_thread = threading.Thread(target=midi_handler.hardware_thread_func, daemon=True)

state_thread.start()
software_thread.start()
hardware_thread.start()

# Simulate hardware messages
for i in range(10):
    midi_handler.hardware_msgs_queue.put({'key': f'note_{i}', 'value': i})
    time.sleep(0.05)

midi_handler.stop()

state_thread.join()
software_thread.join()
hardware_thread.join()
