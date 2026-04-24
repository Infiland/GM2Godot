def emit_prelude(lines, function_names):
    if "_on_no_more_lives" in function_names:
        lines.append(
            "\n\nvar lives = 0:"
            "\n\tset(value):"
            "\n\t\tlives = value"
            "\n\t\tif lives <= 0:"
            "\n\t\t\t_on_no_more_lives()\n"
        )
    if "_on_no_more_health" in function_names:
        lines.append(
            "\n\nvar health = 100:"
            "\n\tset(value):"
            "\n\t\thealth = value"
            "\n\t\tif health <= 0:"
            "\n\t\t\t_on_no_more_health()\n"
        )
