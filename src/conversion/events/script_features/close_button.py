from src.conversion.events.base import EventMapping


_CLOSE_BUTTON_FUNC = "_notification"
_READY_FUNC = "_ready"
_DISABLE_AUTO_QUIT_BODY = "\tget_tree().auto_accept_quit = false"


def get_additional_functions(function_names: set[str]) -> list[EventMapping]:
    if _CLOSE_BUTTON_FUNC in function_names and _READY_FUNC not in function_names:
        return [EventMapping(_READY_FUNC, "", 0, "")]
    return []


def wrap_body(func: EventMapping, body: str, function_names: set[str]) -> str:
    if _CLOSE_BUTTON_FUNC not in function_names:
        return body

    if func.godot_func == _READY_FUNC:
        return f"{_DISABLE_AUTO_QUIT_BODY}\n{body}"
    if func.godot_func == _CLOSE_BUTTON_FUNC:
        return "\tif what == NOTIFICATION_WM_CLOSE_REQUEST:\n" + _indent_body(body)
    return body


def _indent_body(body: str) -> str:
    return "\n".join(f"\t{line}" if line else line for line in body.splitlines())
