#!/usr/bin/env python3
"""
openpilot side of the serial steering MDX longitudinal modes (opendbc/sunnypilot/car/honda/nidec_long).

- The mode param "HondaNidecLongMode" reaches opendbc through sunnypilot's car-specific params list
  (sunnypilot/selfdrive/car/interfaces.py initialize_params -> opendbc sunnypilot setup_interfaces).
- setup_honda_nidec_long_store() gives the car controller a store backed by the "HondaNidecLongState" param, written
  in a background thread so the car process never blocks on disk.

Command line (on the device, from /data/openpilot):
  python3 -m openpilot.sunnypilot.selfdrive.car.honda_nidec_long show            # mode + learned values
  python3 -m openpilot.sunnypilot.selfdrive.car.honda_nidec_long mode 2          # 0 stock, 1 mapped, 2 adaptive
  python3 -m openpilot.sunnypilot.selfdrive.car.honda_nidec_long export FILE     # save learned values to a JSON file
  python3 -m openpilot.sunnypilot.selfdrive.car.honda_nidec_long import FILE     # load them back (e.g. fresh install)
  python3 -m openpilot.sunnypilot.selfdrive.car.honda_nidec_long reset           # forget learned values
The exported file can also be committed as opendbc/sunnypilot/car/honda/nidec_long/learned_seed.json, which is used
whenever the device has no stored values. Mode/import/reset take effect the next time the car starts (go offroad).
"""
import json
import sys
import threading
from queue import Empty, Queue

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

MODE_KEY = "HondaNidecLongMode"
STATE_KEY = "HondaNidecLongState"


class ParamsNidecLongStore:
  def __init__(self, params: Params | None = None):
    self.params = params or Params()
    self._queue: Queue = Queue()
    self._thread = threading.Thread(target=self._run, name="honda-nidec-long-store", daemon=True)
    self._thread.start()

  def load(self) -> dict | None:
    try:
      value = self.params.get(STATE_KEY)
      return value if isinstance(value, dict) else None
    except Exception:
      cloudlog.exception("honda_nidec_long: failed to read learned state")
      return None

  def save(self, record: dict) -> None:
    self._queue.put(record)  # non-blocking for the car process

  def _run(self) -> None:
    while True:
      record = self._queue.get()
      try:
        while True:  # only the newest snapshot matters
          record = self._queue.get_nowait()
      except Empty:
        pass
      try:
        self.params.put(STATE_KEY, record)
      except Exception:
        cloudlog.exception("honda_nidec_long: failed to write learned state")


def setup_honda_nidec_long_store(CI, params: Params | None = None) -> None:
  CC = getattr(CI, "CC", None)
  if CC is None or not hasattr(CC, "nidec_long_store"):
    return
  CC.nidec_long_store = ParamsNidecLongStore(params)


def _main(argv: list[str]) -> int:
  params = Params()
  cmd = argv[1] if len(argv) > 1 else "show"
  if cmd == "show":
    print("mode:", params.get(MODE_KEY, return_default=True), "(0 stock, 1 mapped, 2 adaptive)")
    print(json.dumps(params.get(STATE_KEY), indent=2))
  elif cmd == "mode" and len(argv) > 2:
    params.put(MODE_KEY, int(argv[2]))
    print("mode set to", int(argv[2]), "- applies the next time the car starts")
  elif cmd == "export" and len(argv) > 2:
    state = params.get(STATE_KEY)
    if not isinstance(state, dict):
      print("no learned values stored yet")
      return 1
    with open(argv[2], "w", encoding="utf-8") as f:
      json.dump(state, f, indent=2)
    print("exported to", argv[2])
  elif cmd == "import" and len(argv) > 2:
    with open(argv[2], encoding="utf-8") as f:
      state = json.load(f)
    if not (isinstance(state, dict) and isinstance(state.get("values"), dict)):
      print("not a learned-values file")
      return 1
    params.put(STATE_KEY, state)
    print("imported", len(state["values"]), "values - applies the next time the car starts")
  elif cmd == "reset":
    params.remove(STATE_KEY)
    print("learned values cleared")
  else:
    print(__doc__)
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(_main(sys.argv))
