"""
Schedules a pmset wake 70 minutes before today's first MLB game.
Called by auto_picks.sh when picks haven't run yet and first game is > 110 min away.
Runs as root (LaunchDaemon) so pmset needs no sudo.
"""
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.get_first_game_time import minutes_to_first_game

WAKE_LEAD_MINUTES = 70
FALLBACK_CHECKIN_HOUR = 9  # local time to re-check on days with no games (e.g. All-Star break)


def schedule_wake() -> None:
    mins = minutes_to_first_game()
    if mins == 9999:
        # No games today (off-day / All-Star break). Schedule a check-in wake
        # for tomorrow morning so the daemon re-checks once games resume,
        # instead of leaving the Mac asleep indefinitely with nothing to wake it.
        now_local = datetime.now(ZoneInfo("America/Chicago"))
        tomorrow = (now_local + timedelta(days=1)).replace(
            hour=FALLBACK_CHECKIN_HOUR, minute=0, second=0, microsecond=0
        )
        pmset_fmt = tomorrow.strftime("%m/%d/%y %H:%M:%S")
        result = subprocess.run(["pmset", "schedule", "wake", pmset_fmt], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[schedule_wake] ERROR: pmset failed (rc={result.returncode}): {result.stderr.strip()}")
        else:
            print(f"[schedule_wake] No games today — check-in wake scheduled for {pmset_fmt} CT")
        return

    wake_offset = mins - WAKE_LEAD_MINUTES
    if wake_offset <= 0:
        return  # too late to schedule a useful wake

    wake_time = datetime.now(timezone.utc) + timedelta(minutes=wake_offset)
    local_wake = wake_time.astimezone(ZoneInfo("America/Chicago"))
    pmset_fmt = local_wake.strftime("%m/%d/%y %H:%M:%S")

    result = subprocess.run(["pmset", "schedule", "wake", pmset_fmt], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[schedule_wake] ERROR: pmset failed (rc={result.returncode}): {result.stderr.strip()}")
    else:
        print(f"[schedule_wake] Wake scheduled for {pmset_fmt} CT ({wake_offset}min from now)")


if __name__ == "__main__":
    schedule_wake()
