"""Which object events can run the rest of the event after instance_change.

instance_change gives the calling instance the new object's script, and Godot
frees the script instance it replaces, so the node's script may only change
where no method of the old script that goes on using its members is running
(see the runtime's 76_instance_change.gd). The runtime itself calls the Create,
Step, Alarm, collision and input events of an instance, with nothing of the
instance's script running below them; the converter compiles an
instance_change statement of these events with the rest of the event as a
function it runs after the change. Other events can be called from within
other code of the instance (the Destroy and Clean Up events run inside the
code that destroys the instance, the user events inside the event that
raised them), and keep the change that waits for the event to return.
"""

from __future__ import annotations

import re

_RUNTIME_DISPATCHED_EVENT_RE = re.compile(
    r"^(?:_ready|_on_begin_step|_on_step|_on_end_step|_on_alarm_\d+|_on_collision(?:_.+)?"
    r"|_gm_input_(?:keyboard|mouse|key_press|key_release|gesture)_-?\d+)$"
)


def event_runs_rest_after_instance_change(godot_function: str) -> bool:
    """Whether instance_change in this event runs the rest of the event on the new object."""
    return _RUNTIME_DISPATCHED_EVENT_RE.match(godot_function) is not None


def inherited_event_call(godot_function: str, call: str) -> str:
    """The call of the parent's event for event_inherited.

    The child's event goes on running after the call, so the parent's event
    must not replace the node's script meanwhile (gml_event_nesting).
    """
    if not event_runs_rest_after_instance_change(godot_function):
        return call
    return f"GMRuntime.gml_event_nesting += 1\n{call}\nGMRuntime.gml_event_nesting -= 1"
