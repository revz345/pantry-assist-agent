import sys

from pantry_bridge.lock import stop_running_bridge
from pantry_bridge.main import main, run_selftest

if __name__ == "__main__":
    if "--test" in sys.argv:
        run_selftest()
    elif "--stop" in sys.argv:
        stop_running_bridge()
    else:
        import asyncio

        asyncio.run(main())
