# MIDI Lighting Tracker for ShowXpress DMX Lighting Control

This Python service monitors MIDI input messages from the ShowXpress DMX lighting control software and manages MIDI output based on the state of the buttons. It allows users to control the state of individual buttons or clear all button states.

**Note:** This requires setting up a virtual MIDI loopback device, two MIDI input/output USB devices (technically a third from the ProPresenter computer as an output into the merge box) as well as a MIDI Merge box with an output cable going to the input of the primary MIDI device with the secondary device being used as a physical loopback device via the merge box.

## Installation

Ensure you have Python installed on your system. This service requires the `mido` and `psutil` libraries. You can install them using pip:

```bash
pip install mido psutil
```

## Usage

1. **Clone the Repository:**

    ```bash
    git clone https://github.com/NewDayNaz/MidiLightingTracker.git
    ```

2. **Navigate to the Repository:**

    ```bash
    cd MidiLightingTracker
    ```

3. **Run the Python Script:**

    Replace `Your MIDI Device Name` in the script with the name of your MIDI device. You can find the device name by printing the available ports using `mido.get_input_names()` and `mido.get_output_names()`. Replace `"TheLightingController.exe"` with the process name of your ShowXpress DMX lighting control software.

    ```bash
    python miditracker.py
    ```

4. **Control MIDI Output:**

    Once the script is running, it will monitor MIDI input messages from ShowXpress. MIDI output will be controlled based on the state of the buttons in the lighting control software.

5. **Button State Management:**

    - To turn specific buttons off, send a MIDI Off note for the appropriate button note.
    - To turn specific buttons on and only on, send a MIDI On note for the appropriate button note with a velocity of 127.
    - To clear all button states, send a MIDI Off note for 127 and it will clear the state and turn off every active button.
6. **Exit the Script:**

    Press `Ctrl + C` to stop the MIDI state tracking service.

## Dependencies

- `mido`: MIDI message processing library.
- `psutil`: Process and system utilities library.

## Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
