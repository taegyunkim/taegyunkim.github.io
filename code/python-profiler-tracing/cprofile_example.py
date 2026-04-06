# /// script
# requires-python = "==3.15.0a7"
# dependencies = []
# ///

import profiling.tracing
import time


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

# With profiling.tracing
profiler = profiling.tracing.Profile()
profiler.enable()
start = time.perf_counter()
slow_function()
with_profile = time.perf_counter() - start
profiler.disable()

print(f"baseline:    {baseline * 1000:.1f}ms")
print(f"with hook:   {with_profile * 1000:.1f}ms")
print(f"overhead:    {with_profile / baseline:.1f}x")
print()

# getstats() returns _lsprof.profiler_entry objects:
#   entry.callcount   - number of calls
#   entry.inlinetime  - time in the function itself, excluding callees (tottime)
#   entry.totaltime   - time including callees (cumtime)
entries = sorted(profiler.getstats(), key=lambda e: -e.totaltime)
print(f"{'ncalls':>10}  {'tottime':>12}  {'cumtime':>12}  function")
for entry in entries:
    if not hasattr(entry.code, "co_qualname"):
        continue  # skip C functions
    name = f"{entry.code.co_filename.split('/')[-1]}:{entry.code.co_firstlineno}({entry.code.co_qualname})"
    print(f"{entry.callcount:>10}  {entry.inlinetime * 1000:>10.2f}ms  {entry.totaltime * 1000:>10.2f}ms  {name}")
