"""Bounded observation retries. Never replay an input or swallow focus/stop errors."""
import time
import control

def retry_observation(capture,observe,timeout=3,interval=.12):
    deadline=time.monotonic()+timeout
    while True:
        control.check()
        frame=capture();value=observe(frame)
        if value is not None: return frame,value
        if time.monotonic()>=deadline: return frame,None
        time.sleep(min(interval,max(0,deadline-time.monotonic())))
