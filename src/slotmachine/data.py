from collections import namedtuple

Talk = namedtuple(
    "Talk",
    ("id", "duration", "venues", "speakers", "slot_intervals", "preferred_venues", "preferred_intervals"),
)
# If slot_intervals, preferred venues and/or slots are not specified, assume no restrictions/preferences
Talk.__new__.__defaults__ = ([], [], [])
