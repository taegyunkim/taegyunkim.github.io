---
publish: true
title: "Python Async: From the Ground Up"
date: 2026-04-06
tags:
  - python
  - async
  - profiling
---

Python async trips people up because the mental model isn't obvious. This post builds it from scratch: what async actually is, how the event loop works, what coroutines and tasks are, and when you actually want it.

## What Is Async?

Async is a way to do multiple things at once *in a single thread*, by cooperatively yielding control during waits.

The key word is **cooperative**. In async code, a running coroutine holds the thread until it explicitly yields by hitting an `await`. That `await` is the handoff point: "I'm waiting for something; run something else in the meantime."

Contrast with threads: threads are **preemptive**. The OS can interrupt a thread at any time and switch to another. Async is simpler (no data races from mid-instruction preemption) but requires your code to actually yield.

Contrast with processes: processes have separate memory. Async shares memory but stays single-threaded.

The practical consequence: async shines when your workload is **I/O-bound**, waiting on network calls, disk reads, database queries. If you're CPU-bound, async won't help (you're never waiting, so you never yield).

---

## How It Works: The Event Loop

The runtime engine of Python async is the **event loop**. It's a loop that:

1. Picks the next ready-to-run task
2. Runs it until it hits an `await` (suspension point)
3. When the awaited thing completes (e.g. a socket becomes readable), marks the task ready again
4. Repeat

This core scheduling logic lives in [`BaseEventLoop._run_once`](https://github.com/python/cpython/blob/v3.15.0a7/Lib/asyncio/base_events.py#L1977) in CPython.

Under the hood, the event loop uses OS primitives (`epoll` on Linux, `kqueue` on macOS) to monitor many file descriptors simultaneously without blocking.

```python
import asyncio

async def main():
    await asyncio.sleep(1)   # suspends here, event loop runs other tasks
    print("done")

asyncio.run(main())          # creates the event loop and runs until main() completes
```

[`asyncio.run(coro, *, debug=None, loop_factory=None)`](https://docs.python.org/3/library/asyncio-runner.html#asyncio.run) is the standard entrypoint. It creates a fresh event loop, runs the coroutine you give it, then tears the loop down.

---

## What Is a Coroutine?

A **coroutine** is the object you get when you call an `async def` function. Calling the function does *not* execute it. It just creates the coroutine object.

```python
async def fetch(url):
    ...

coro = fetch("https://example.com")  # nothing has run yet
```

Python generators are objects that can pause and resume. When you call `.send(None)` on a generator, it runs until the next `yield`, then pauses and returns the yielded value. When the function returns, it raises `StopIteration`. This pause/resume contract is the [generator protocol](https://docs.python.org/3/reference/expressions.html#generator-iterator-methods).

Coroutines use the same protocol. `async def` functions return a [coroutine object](https://docs.python.org/3/reference/datamodel.html#coroutine-objects) that also implements `.send()` and `.throw()`. An `await` expression may pause the coroutine, but only if the awaited object isn't already done. If it is already done, the coroutine runs straight through without suspending. If it isn't, the coroutine yields control back to the event loop and waits.

The event loop always calls [`.send(None)`](https://github.com/python/cpython/blob/v3.15.0a7/Lib/asyncio/tasks.py#L289). The result doesn't flow through `send()` at all. Instead, [`Future.__await__`](https://github.com/python/cpython/blob/v3.15.0a7/Lib/asyncio/futures.py#L296) yields the future object itself to signal the Task to wait, and when the future completes and `.send(None)` is called again to resume, `__await__` returns `self.result()` directly, which becomes the value of the `await` expression.

To actually run a coroutine, you either:
- `await` it from another coroutine
- Wrap it in a [`Task`](https://docs.python.org/3/library/asyncio-task.html#asyncio.Task) (schedules it to run concurrently)

---

## What Is a Task?

An [`asyncio.Task`](https://docs.python.org/3/library/asyncio-task.html#asyncio.Task) wraps a coroutine and schedules it on the event loop. Creating a task allows coroutines to run *concurrently*:

```python
async def main():
    # These run concurrently; both start before either is awaited
    task1 = asyncio.create_task(fetch("service-a"))
    task2 = asyncio.create_task(fetch("service-b"))

    result1 = await task1
    result2 = await task2
```

`Task` is a subclass of [`Future`](https://docs.python.org/3/library/asyncio-future.html#asyncio.Future). A `Future` represents a value that isn't ready yet. You can `await` it to pause until the value arrives.

The distinction:
- **Coroutine**: lazy, not running. Just an object.
- **Task**: a coroutine that has been submitted to the event loop. It will run.

---

## Eager vs. Lazy Tasks

By default, tasks are **lazy**: [`asyncio.create_task()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task) schedules the coroutine to run *later*, on the next iteration of the event loop. The current coroutine keeps running until it hits an `await`.

Python 3.12 introduced **eager task execution** via [`asyncio.eager_task_factory`](https://docs.python.org/3/library/asyncio-task.html#asyncio.eager_task_factory). With eager tasks, `create_task()` immediately runs the coroutine to its first suspension point before returning. If the coroutine completes synchronously (no actual I/O), it finishes entirely without ever touching the scheduler.

```python
# Python 3.12+
async def main():
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asyncio.eager_task_factory)
    ...

asyncio.run(main())
```

Eager tasks reduce latency for tasks that return quickly and avoid unnecessary round-trips through the scheduler.

---

## Why Use Async? An AI Agent Example

A common pattern in LLM-based applications: before calling the LLM, you need to assemble context from several independent sources — a vector database, user history, user preferences. All three are network-bound and independent of each other, so there's no reason to wait for one before starting the next.

With synchronous code:

```python
import time

def fetch_vector_context(query, delay):
    time.sleep(delay)
    return f"context: top docs for '{query}'"

def fetch_user_history(user_id, delay):
    time.sleep(delay)
    return f"history: last 5 queries for user {user_id}"

def fetch_user_preferences(user_id, delay):
    time.sleep(delay)
    return f"preferences: for user {user_id}"

def call_llm(prompt):
    time.sleep(1.5)
    return f"LLM response to: {prompt}"

def handle_query(user_id, query):
    vector_context   = fetch_vector_context(query,   0.8)   # wait 0.8s
    user_history     = fetch_user_history(user_id,   0.5)   # wait another 0.5s
    user_preferences = fetch_user_preferences(user_id, 0.3) # wait another 0.3s
    prompt = f"{query}\n{vector_context}\n{user_history}\n{user_preferences}"
    return call_llm(prompt)                                  # wait another 1.5s
    # Total: 3.1 seconds

start = time.time()
handle_query("user-42", "how do I profile async Python?")
print(f"{time.time() - start:.2f}s")   # 3.10s
```

With async, the three independent fetches run concurrently:

```python
import asyncio
import time

async def fetch_vector_context(query, delay):
    await asyncio.sleep(delay)
    return f"context: top docs for '{query}'"

async def fetch_user_history(user_id, delay):
    await asyncio.sleep(delay)
    return f"history: last 5 queries for user {user_id}"

async def fetch_user_preferences(user_id, delay):
    await asyncio.sleep(delay)
    return f"preferences: for user {user_id}"

async def call_llm(prompt):
    await asyncio.sleep(1.5)
    return f"LLM response to: {prompt}"

async def handle_query(user_id, query):
    vector_context, user_history, user_preferences = await asyncio.gather(
        fetch_vector_context(query,     0.8),
        fetch_user_history(user_id,     0.5),
        fetch_user_preferences(user_id, 0.3),
    )
    prompt = f"{query}\n{vector_context}\n{user_history}\n{user_preferences}"
    return await call_llm(prompt)
    # Total: 0.8s (gather) + 1.5s (LLM) = 2.3 seconds

start = time.time()
asyncio.run(handle_query("user-42", "how do I profile async Python?"))
print(f"{time.time() - start:.2f}s")   # 2.30s
```

[`asyncio.gather()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather) runs the three fetches concurrently and waits for all of them. The LLM call then follows with the assembled context. Total time drops from 3.1s to 2.3s — the parallel fetches collapse to the slowest one (0.8s), and the LLM call is sequential because it depends on the results.

This pattern, fan-out then fan-in, is where async pays off most directly.

---

## Common Async Libraries in Python

**Core**
- [**asyncio**](https://github.com/python/cpython/tree/v3.15.0a7/Lib/asyncio): the stdlib event loop. Everything else builds on top of it.
- [**uvloop**](https://github.com/MagicStack/uvloop): drop-in replacement for the asyncio event loop, 2-4x faster (wraps libuv, same library that powers Node.js).

**Alternative runtimes**
- [**Trio**](https://github.com/python-trio/trio): a different take on async Python with structured concurrency built in. More opinionated, harder to misuse.
- [**AnyIO**](https://github.com/agronholm/anyio): abstraction layer that runs on both asyncio and Trio. Write once, works on both.
- [**gevent**](https://github.com/gevent/gevent): takes a different approach entirely. Instead of `async`/`await`, it uses greenlets: lightweight coroutines that are switched cooperatively by monkey-patching the standard library. Existing synchronous code (like `socket`, `threading`) works without modification; gevent swaps the blocking calls out from under it. Older than asyncio and still widely used in production.

---

## What Async Doesn't Fix

A few common misconceptions:

**CPU-bound work**: `asyncio.sleep()` yields because it's waiting. A tight loop computing a hash does not yield. It holds the thread the entire time, starving other coroutines. For CPU-bound work, you still need processes (`multiprocessing`, `ProcessPoolExecutor`) or, in Python 3.13+, free-threaded Python.

**Blocking calls**: If you call a synchronous blocking function inside a coroutine (`time.sleep()`, a blocking DB driver, `open()` on a slow NFS mount), you block the event loop entirely. The fix is [`asyncio.to_thread()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread) to run it in a thread pool.

**Simplicity**: Async code can be harder to reason about than sequential code. Stack traces are harder to read, debugging is trickier, and "function coloring" (async functions can only be awaited from async contexts) spreads through a codebase.

Use async when I/O concurrency is the bottleneck. Don't use it because it sounds fast.
