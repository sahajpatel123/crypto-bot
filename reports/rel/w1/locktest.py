import sys, time
from cryptobot.app.store import RunStore, StoreLocked
s = RunStore("/tmp/w1-rel/lock.db")
if sys.argv[1] == "hold":
    s.acquire_lock(); print("holder: locked", flush=True); time.sleep(4)
else:
    time.sleep(1)
    try:
        s.acquire_lock(); print("TAKEOVER-BUG")
    except StoreLocked as e:
        print("second refused ok:", str(e)[:60])
