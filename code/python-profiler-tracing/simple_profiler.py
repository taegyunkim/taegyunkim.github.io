# /// script
# requires-python = "==3.15.0a7"
# dependencies = []
# ///

import sys
import time
import threading
from collections import defaultdict


class SimpleProfiler:
    def __init__(self):
        self.totals = defaultdict(float)  # function name -> total seconds
        self._call_times = {}             # frame id -> entry time

    def _hook(self, frame, event, arg):
        if event == "call":
            self._call_times[id(frame)] = time.perf_counter()

        elif event == "return":
            entry = self._call_times.pop(id(frame), None)
            if entry is not None:
                elapsed = time.perf_counter() - entry
                name = frame.f_code.co_qualname
                self.totals[name] += elapsed

    def start(self):
        sys.setprofile(self._hook)
        threading.setprofile(self._hook)

    def stop(self):
        sys.setprofile(None)
        threading.setprofile(None)

    def report(self):
        for name, total in sorted(self.totals.items(), key=lambda x: -x[1]):
            if total >= 0.0001:  # skip sub-0.1ms noise from profiler internals
                print(f"{total * 1000:8.2f}ms  {name}")


def add(a, b):
    return a + b


def slow_function():
    total = 0
    for i in range(1_000_000):
        total = add(total, i)
    return total


profiler = SimpleProfiler()
profiler.start()
slow_function()
profiler.stop()
profiler.report()
