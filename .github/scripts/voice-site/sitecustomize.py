"""Apply narrow runner plumbing to every unchanged native Python child."""
import os
if os.environ.get("AGMM_VOICE_CHILD") == "1":
    try:
        from voice_effects import install
        install()
    except BaseException:
        # Python otherwise prints a sitecustomize error and continues, which
        # would silently run an unguarded provider child.
        os._exit(78)
if os.environ.get("AGMM_BUILD_CHILD") == "1":
    try:
        from native_build_effects import install
        install()
    except BaseException:
        os._exit(78)
