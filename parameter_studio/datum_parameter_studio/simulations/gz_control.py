"""Isolated Gazebo transport client for synchronous world-control requests."""
import ctypes
import json
import os
import signal
import sys

from .gazebo import bindings


def main():
    expected_parent = int(os.environ['DATUM_GZ_PARENT_PID'])
    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)
    if os.getppid() != expected_parent:
        return
    transport, messages = bindings()
    node = transport.Node()
    for line in sys.stdin:
        try:
            fields = json.loads(line)
            ok, reply = node.request('/world/datum/control', messages['world_control'].WorldControl(**fields),
                                     messages['world_control'].WorldControl, messages['boolean'].Boolean, 1000)
            print(json.dumps({'ok': bool(ok and reply.data)}), flush=True)
        except Exception:
            print(json.dumps({'ok': False}), flush=True)


if __name__ == '__main__':
    main()
