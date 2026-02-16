def get_offset_age_color(age_seconds: float) -> str:
    if age_seconds > 290:
        return "bold red"
    elif age_seconds > 270:
        return "yellow"
    return "green"


def byte_size_to_gb(byte_size: int) -> float:
    return byte_size / (1024**3)


def make_battery_bar(level: float) -> str:
    """Generate a rich text battery bar."""
    segments = int(level / 20)
    if segments > 5:
        segments = 5

    color = "green"
    if level < 20:
        color = "red"
    elif level < 40:
        color = "yellow"

    filled = "█" * segments
    empty = "░" * (5 - segments)

    return f"[{color}]{filled}{empty}[/] {level:.0f}%"


def make_signal_bar(rtt_ms: float) -> str:
    """Generate a rich text signal strength indicator with value."""
    if rtt_ms < 5:
        return f"[green]▃▅▇[/] ({rtt_ms:.1f}ms)"
    elif rtt_ms < 30:
        return f"[green]▃▅[/][dim]░[/] ({rtt_ms:.1f}ms)"
    elif rtt_ms < 100:
        return f"[yellow]▃[/][dim]░░[/] ({rtt_ms:.1f}ms)"
    else:
        return f"[red]_[/][dim]░░[/] ({rtt_ms:.1f}ms)"
