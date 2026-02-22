"""Static schedule entries for the badge UI.

Tuple-of-tuples: (day, start, end, title, speaker, location)
"""

from cactuscon import config
from cactuscon.utils import Logger

# Keep entries short for small screens; replace with real schedule as needed.
SCHEDULE_ENTRIES = (
    ("Friday", "09:30", "10:00", "Opening Ceremony", "", "Track 1"),
    ("Friday", "09:30", "13:30", "Gotta Contain \'Em All: Collaborative Incident Response Training Through Gaming", "Glen Sorensen, Klaus Agnoletti", "Workshop"),
    ("Friday", "10:00", "11:00", "LLMs Gone Wild: AI-Crafted Malware Infecting Our Supply Chain", "Mackenzie", "Track 1"),
    ("Friday", "10:00", "11:00", "Pathways to Pentesting ", "heisenberg", "Track 2"),
    ("Friday", "10:00", "11:00", "Stealing From Thieves", "Juan Pablo Gomez Postigo, Nicholas Anastasi", "Track 3"),
    ("Friday", "11:00", "12:00", "Cloud ForeverDays: Cloud Vulnerabilities That Refuse To Die", "strandjs", "Track 1"),
    ("Friday", "11:00", "12:00", "Agents Under Siege: Live Attacks from RAG to Tool Calls to Protocols", "Aviral Srivastava", "Track 2"),
    ("Friday", "11:00", "12:00", "A History of AppSec through Neopets.com", "Katie Paxton-Fear", "Track 3"),
    ("Friday", "12:00", "13:00", "Lunch", "", "Track 1"),
    ("Friday", "13:00", "14:00", "Keynote: Death by Ransomware", "quaddi", "Track 1"),
    ("Friday", "14:00", "15:00", "AI Has Changed the Game -- But Not All the Rules: Old Threats, New Risks, Real Consequences", "Lester Godsey", "Track 1"),
    ("Friday", "14:00", "15:00", "Exploiting Consumer Networking Hardware Start To Finish", "Average Joe", "Track 2"),
    ("Friday", "14:00", "15:00", "YubiWorm: Turning a Trusted YubiKey into a Propagating Worm", "Jordan Lanham", "Track 3"),
    ("Friday", "14:00", "17:05", "Rooting Around: A Linux Rootkit Workshop", "Royce, 0xtengu", "Workshop"),
    ("Friday", "15:00", "15:30", "They Weaponised Your AI CLI: Unpacking the Nx \'s1ngularity\' npm Compromise", "Kevin Murrietta", "Track 1"),
    ("Friday", "15:00", "15:30", "Sharpening Python Tools with Rust", "TheTechromancer", "Track 3"),
    ("Friday", "15:00", "16:00", "Evading EDR with the Wasm Blindspot", "Dan \"AltF4\" Petro", "Track 2"),
    ("Friday", "15:30", "16:00", "Breaking Model Context Protocol: Back to Security Basics", "Brooks McMillin", "Track 1"),
    ("Friday", "16:00", "16:30", "Oops All Passwords: Malware Coming Soon Near You!", "Robert Meylor", "Track 1"),
    ("Friday", "16:30", "18:00", "Happy Hour - Sponsored by Vertex", "", "Track 1"),
    ("Friday", "18:00", "19:30", "Afterparty - Sponsored by Arctic Wolf", "", "Track 1"),
    ("Saturday", "09:00", "13:00", "Advanced Web Threats: A Hands-On Exploitation Workshop", "Anthony Pipia", "Workshop"),
    ("Saturday", "09:30", "10:30", "Cross-Site Scripting: Old Bug, New Tricks", "Sonal Shrivastava", "Track 1"),
    ("Saturday", "09:30", "10:30", "The Badge Talk!", "fg, cybaix", "Track 2"),
    ("Saturday", "09:30", "10:30", "CTRL+ESC+HOST: A Look at Evasive Compromise Paths, Kicking Kiosks and Taking ADCs", "Ezra Woods, CroodSolutions", "Track 3"),
    ("Saturday", "10:30", "11:00", "All Systems GO! Attention Satellite Space Nerds & Hackers, AMSAT build your own Cubesat!", "@SecureAerospace, Henry Danielson Hankashyyyk", "Track 1"),
    ("Saturday", "10:30", "11:00", "This Little Brite of Mine: Mobile Forensics for Fun and (Sometimes) Profit", "w1nd_w4lk3r", "Track 2"),
    ("Saturday", "10:30", "11:00", "Cyber Defenders: Turning Skills Into Lifesaving Action", "Kristen Sanders", "Track 3"),
    ("Saturday", "11:00", "11:30", "OopsSec: The Day I Made the DMV Even Slower", "GingerHacker", "Track 1"),
    ("Saturday", "11:00", "12:00", "The Hardware Procurement Iceberg: A Framework For Keeping Embedded Research Fun, Cheap, and Ethical", "yltsi", "Track 2"),
    ("Saturday", "11:00", "12:00", "Those \"Spooky Boxes\" are still more than Spooky", "D3ad4ss", "Track 3"),
    ("Saturday", "11:30", "12:00", "Worst of Cybersecurity Reporting 2025", "Yael Grauer, huertanix", "Track 1"),
    ("Saturday", "12:00", "13:00", "Lunch", "", "Track 1"),
    ("Saturday", "13:00", "14:00", "Keynote: The Importance of Being Human", "Selena Larson", "Track 1"),
    ("Saturday", "14:00", "15:00", "Sipping From the CVE Firehose: Prioritizing Emerging Threats for Real-World Impact", "Nate Robb", "Track 1"),
    ("Saturday", "14:00", "15:00", "Dungeons & Dragons: The security tool you didn\'t know you needed", "Glen Sorensen, Klaus Agnoletti", "Track 2"),
    ("Saturday", "14:00", "15:00", "The Folly of Rewarding A While Hoping for B: Ethics and Metrics in Cybersecurity", "Casey Beaumont", "Track 3"),
    ("Saturday", "14:00", "17:00", "Red Teaming Agentic AI: Hands-On Labs with MCPs, OWASP, and MITRE", "Peter Hefley, Prosecdom", "Workshop"),
    ("Saturday", "15:00", "16:00", "CTI Bingo: RMM Abuse, Supply Chains, and EDR Killers", "Josh Carolan, Bobby Venal, Fire", "Track 1"),
    ("Saturday", "15:00", "16:00", "The Serverless Mirage: Navigating Risks in an Invisible Infrastructure", "Nimish, Shivam Dhar", "Track 2"),
    ("Saturday", "15:00", "16:00", "Bootstrapping Payloads One Game at a Time", "Royce, 0xtengu", "Track 3"),
    ("Saturday", "16:00", "16:30", "Closing", "", "Track 1"),
)


_LOGGER = Logger(config.LOG_LEVEL)
_LOGGED_STATS = False

# Caches for derived indices (lazy)
_INDEX_READY = False
_entries_by_day = {}
_entries_by_day_track = {}
_timeslots_by_day = {}


def entry_count():
    return len(SCHEDULE_ENTRIES)


def approx_string_bytes():
    # Rough estimate: sum of all string lengths (does not include object overhead).
    total = 0
    for day, start, end, title, speaker, location in SCHEDULE_ENTRIES:
        total += (
            len(day)
            + len(start)
            + len(end)
            + len(title)
            + len(speaker)
            + len(location)
        )
    return total


def _log_stats_once():
    global _LOGGED_STATS
    if _LOGGED_STATS:
        return
    _LOGGED_STATS = True
    _LOGGER.info(
        f"Schedule entries: {entry_count()}, approx string bytes: {approx_string_bytes()} (overhead not included)"
    )


def get_days():
    # Preserve first-seen order from data.
    seen = []
    for day, _, _, _, _, _ in SCHEDULE_ENTRIES:
        if day not in seen:
            seen.append(day)
    return tuple(seen)


def get_tracks():
    # Fixed order.
    return ("Track 1", "Track 2", "Track 3", "Workshops")


def parse_hhmm(hhmm):
    parts = hhmm.split(":")
    if len(parts) != 2:
        return 0
    return int(parts[0]) * 60 + int(parts[1])


def format_hhmm(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _ensure_indexes():
    global _INDEX_READY, _entries_by_day, _entries_by_day_track, _timeslots_by_day
    if _INDEX_READY:
        return

    _entries_by_day = {}
    _entries_by_day_track = {}
    _timeslots_by_day = {}

    track_set = set(get_tracks())

    for entry in SCHEDULE_ENTRIES:
        day, start, end, title, speaker, location = entry

        # entries_by_day
        _entries_by_day.setdefault(day, []).append(entry)

        # entries_by_day_track
        if location in track_set:
            day_tracks = _entries_by_day_track.setdefault(day, {})
            day_tracks.setdefault(location, []).append(entry)

        # timeslots_by_day (unique start times)
        start_min = parse_hhmm(start)
        _timeslots_by_day.setdefault(day, set()).add(start_min)

    # Sort per day lists
    for day, entries in _entries_by_day.items():
        entries.sort(key=lambda e: parse_hhmm(e[1]))

    for day, tracks in _entries_by_day_track.items():
        for track, entries in tracks.items():
            entries.sort(key=lambda e: parse_hhmm(e[1]))

    for day, timeslots in _timeslots_by_day.items():
        _timeslots_by_day[day] = sorted(timeslots)

    _INDEX_READY = True


def get_entries_by_day(day):
    _ensure_indexes()
    return _entries_by_day.get(day, [])


def get_entries_by_day_track(day, track):
    _ensure_indexes()
    return _entries_by_day_track.get(day, {}).get(track, [])


def get_timeslots_by_day(day):
    _ensure_indexes()
    return _timeslots_by_day.get(day, [])


# Log once when module is imported.
_log_stats_once()
