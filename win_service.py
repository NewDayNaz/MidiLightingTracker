import win32serviceutil
import win32service
import win32event
import servicemanager
import win32api
import time
import sys
import miditracker  # Import your script

class MyService(win32serviceutil.ServiceFramework):
    _svc_name_ = "MidiTracker"
    _svc_display_name_ = "MIDI State Tracker"
    _svc_description_ = "Tracks the sate of the lighting console over MIDI"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        time.sleep(2)
        miditracker.stop()

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        self.main()

    def main(self):
        # Start your script here
        miditracker.main()
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(MyService)