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
        self.totals = defaultdict(float)
        self._call_times = {}

    def _hook(self, frame, event, arg):
        if event == "call":
            self._call_times[id(frame)] = time.perf_counter()
        elif event == "return":
            entry = self._call_times.pop(id(frame), None)
            if entry is not None:
                elapsed = time.perf_counter() - entry
                self.totals[frame.f_code.co_qualname] += elapsed

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


# Baseline: no profiler
start = time.perf_counter()
slow_function()
baseline = time.perf_counter() - start

# With profiler
profiler = SimpleProfiler()
profiler.start()
start = time.perf_counter()
slow_function()
with_profile = time.perf_counter() - start
profiler.stop()

print(f"baseline:    {baseline * 1000:.1f}ms")
print(f"with hook:   {with_profile * 1000:.1f}ms")
print(f"overhead:    {with_profile / baseline:.1f}x")
print()
profiler.report()
