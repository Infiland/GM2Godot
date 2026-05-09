from src.conversion.events.base import EventMapping


_READY_FUNC = "_ready"
_RESIZE_FUNC = "_on_resize"
_CONNECT_RESIZE_BODY = "\tget_viewport().size_changed.connect(_on_resize)"


def get_additional_functions(function_names: set[str]) -> list[EventMapping]:
    if _RESIZE_FUNC in function_names and _READY_FUNC not in function_names:
        return [EventMapping(_READY_FUNC, "", 0, "")]
    return []


def wrap_body(func: EventMapping, body: str, function_names: set[str]) -> str:
    if _RESIZE_FUNC in function_names and func.godot_func == _READY_FUNC:
        return f"{_CONNECT_RESIZE_BODY}\n{body}"
    return body
