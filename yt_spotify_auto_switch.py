import asyncio
import sys
import time
from typing import List, Optional
import threading

try:
    # Windows 10/11 media control APIs
    import winsdk.windows.media.control as wmc
    import winsdk.windows.foundation as wf
except Exception as e:
    print("Failed to import winsdk. Make sure you have installed requirements with: pip install -r requirements.txt")
    raise

# Global hotkey support to exit quickly
try:
    import keyboard  # type: ignore
except Exception:
    keyboard = None

# ------------------------------
# Configuration
# ------------------------------
# We treat any active media session from these apps as a potential video source
BROWSER_AUMID_KEYWORDS = [
    "chrome", "msedge", "edge", "firefox", "brave", "opera", "vivaldi", "msedgewebview", "webview2"
]

# Identify Spotify sessions by AUMID containing this token
SPOTIFY_AUMID_TOKEN = "spotify"

# Polling interval in seconds
POLL_INTERVAL = 0.5

# Global hotkey to stop the app (works in background)
STOP_HOTKEY = "ctrl+alt+x"

# ------------------------------
# Helpers
# ------------------------------
class PlaybackStatus:
    CLOSED = 0
    OPENED = 1
    CHANGING = 2
    STOPPED = 3
    PLAYING = 4
    PAUSED = 5


def is_browser_session(aumid: str) -> bool:
    lid = (aumid or "").lower()
    return any(k in lid for k in BROWSER_AUMID_KEYWORDS)


def is_spotify_session(aumid: str) -> bool:
    return SPOTIFY_AUMID_TOKEN in (aumid or "").lower()


def get_playback_info(session):
    """Return (playback_status:int, playback_type:int|None). Be tolerant to API shape."""
    info = None
    status = None
    ptype = None
    try:
        info = session.get_playback_info()
    except Exception:
        try:
            info = getattr(session, "playback_info", None)
        except Exception:
            info = None
    if info is not None:
        try:
            status = info.playback_status
        except Exception:
            status = None
        try:
            ptype = info.playback_type
        except Exception:
            ptype = None
    return status, ptype


async def get_media_title(session) -> Optional[str]:
    """Try to get media title (best-effort, optional)."""
    try:
        props_op = session.try_get_media_properties_async()
    except AttributeError:
        try:
            props_op = session.get_media_properties_async()
        except Exception:
            props_op = None
    if props_op is None:
        return None
    try:
        props = await props_op
        title = getattr(props, "title", None)
        return title
    except Exception:
        return None


async def request_manager():
    # Request the session manager
    mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
    return mgr


def list_sessions(mgr) -> List:
    try:
        return list(mgr.get_sessions())
    except Exception:
        return []


def pick_spotify_session(sessions: List):
    for s in sessions:
        aumid = getattr(s, "source_app_user_model_id", "")
        if is_spotify_session(aumid):
            return s
    return None


def any_browser_video_playing(sessions: List) -> bool:
    # Consider any browser session with status PLAYING as active video/audio. If playback_type==Video, even better.
    for s in sessions:
        aumid = getattr(s, "source_app_user_model_id", "")
        if not is_browser_session(aumid):
            continue
        status, ptype = get_playback_info(s)
        if status == PlaybackStatus.PLAYING:
            return True
    return False


def get_spotify_playing(s: Optional[object]) -> Optional[bool]:
    if s is None:
        return None
    status, _ = get_playback_info(s)
    if status is None:
        return None
    return status == PlaybackStatus.PLAYING


async def try_spotify_pause(s):
    if s is None:
        return False
    try:
        await s.try_pause_async()
        return True
    except Exception:
        try:
            # Some builds expose methods without awaitable results; ignore
            s.try_pause_async()
            return True
        except Exception:
            return False


async def try_spotify_play(s):
    if s is None:
        return False
    try:
        await s.try_play_async()
        return True
    except Exception:
        try:
            s.try_play_async()
            return True
        except Exception:
            return False


async def monitor_loop(stop_event: threading.Event):
    mgr = await request_manager()

    last_browser_playing = None
    last_spotify_playing = None

    print("Started yt-spotify auto switcher. Ctrl+C or press Ctrl+Alt+X to stop.")

    while not stop_event.is_set():
        sessions = list_sessions(mgr)
        browser_playing = any_browser_video_playing(sessions)
        spotify_session = pick_spotify_session(sessions)
        spotify_playing = get_spotify_playing(spotify_session)

        # On changes in browser playback state, decide Spotify action
        if last_browser_playing is None or browser_playing != last_browser_playing:
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] Browser media is now {'PLAYING' if browser_playing else 'PAUSED/STOPPED'}.")
            if browser_playing:
                # Pause Spotify when browser media plays
                if spotify_playing is not False:  # unknown or playing
                    ok = await try_spotify_pause(spotify_session)
                    if ok:
                        print(f"[{ts}] Paused Spotify.")
            else:
                # Play Spotify when browser media pauses/stops
                if spotify_playing is not True:  # unknown or paused
                    ok = await try_spotify_play(spotify_session)
                    if ok:
                        print(f"[{ts}] Played Spotify.")

        # Also, if Spotify state changed and conflicts with policy, reconcile gently
        # (Optional; comment out if you prefer only reacting to browser changes.)
        if browser_playing and spotify_playing:
            # Browser is playing; Spotify should be paused
            await try_spotify_pause(spotify_session)
        elif (not browser_playing) and (spotify_playing is False):
            # Browser is not playing; Spotify should be playing
            await try_spotify_play(spotify_session)

        last_browser_playing = browser_playing
        last_spotify_playing = spotify_playing

        await asyncio.sleep(POLL_INTERVAL)

    print("Stop signal received. Exiting monitor.")


def setup_hotkey(stop_event: threading.Event):
    """Register a global hotkey to stop the program. Returns a handler id or None."""
    if keyboard is None:
        print("keyboard module not available; global hotkey disabled. Use Ctrl+C in console to exit.")
        return None
    try:
        handler = keyboard.add_hotkey(STOP_HOTKEY, lambda: stop_event.set())
        print(f"Global stop hotkey registered: {STOP_HOTKEY}")
        return handler
    except Exception:
        print("Failed to register global hotkey; you can still exit with Ctrl+C.")
        return None


def main():
    if sys.platform != "win32":
        print("This script only works on Windows 10/11.")
        sys.exit(1)
    stop_event = threading.Event()
    hotkey_handle = setup_hotkey(stop_event)
    try:
        asyncio.run(monitor_loop(stop_event))
    except KeyboardInterrupt:
        print("\nKeyboard interrupt. Exiting.")
    finally:
        try:
            if keyboard is not None:
                if hotkey_handle is not None:
                    keyboard.remove_hotkey(hotkey_handle)
                keyboard.unhook_all_hotkeys()
        except Exception:
            pass


if __name__ == "__main__":
    main()
