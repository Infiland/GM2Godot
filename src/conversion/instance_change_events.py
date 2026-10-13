"""Which object events can run the rest of the event after instance_change.

instance_change gives the calling instance the new object's script, and Godot
frees the script instance it replaces, so the node's script may only change
where no method of the old script that goes on using its members is running
(see the runtime's 76_instance_change.gd). The runtime itself calls the Create,
Step, Alarm, collision, input, Game Start, Room Start and Animation End events
of an instance, with nothing of the instance's script running below them (a
room change is carried out between two steps, and the Animation End event
is raised by the step loop); the converter compiles an instance_change
statement of these events with the rest of the event as a function it runs
after the change. Other events can be called from within other code of the
instance (the Destroy and Clean Up events run inside the code that destroys
the instance, the user events inside the event that raised them), and keep the
change that waits for the event to return.

A child's event reaches its parent's event through event_inherited(), with the
child's method running below the parent's: when the parent's event (or an
ancestor's) can change the object, the child's event ends with that call and
runs the rest of its code as such a function too.
"""

from __future__ import annotations

import re
from collections.abc import Collection

_RUNTIME_DISPATCHED_EVENT_RE = re.compile(
    r"^(?:_ready|_on_begin_step|_on_step|_on_end_step|_on_alarm_\d+|_on_collision(?:_.+)?"
    r"|_on_game_start|_on_room_start|_on_animation_end"
    r"|_gm_input_(?:keyboard|mouse|key_press|key_release|gesture)_-?\d+)$"
)
_INSTANCE_CHANGE_CALL_RE = re.compile(r"\binstance_change\s*\(")


def event_runs_rest_after_instance_change(godot_function: str) -> bool:
    """Whether instance_change in this event runs the rest of the event on the new object."""
    return _RUNTIME_DISPATCHED_EVENT_RE.match(godot_function) is not None


def source_may_continue_instance_change(
    godot_function: str,
    source: str,
    macros: Collection[str] = (),
) -> bool:
    """Whether an event's code may run an instance_change statement with the rest of the event as a function.

    The check is a cheap one on the text (a call in a comment counts too): the
    converter only needs to know whether a child's event_inherited() can reach
    a change of the instance's script. macros are the project's macros that
    expand to instance_change: a statement that is one of them is such a
    statement too.
    """
    if not event_runs_rest_after_instance_change(godot_function):
        return False
    if _INSTANCE_CHANGE_CALL_RE.search(source) is not None:
        return True
    return any(re.search(rf"\b{re.escape(name)}\b", source) is not None for name in macros)
