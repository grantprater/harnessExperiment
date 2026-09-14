"""Event selection and projection utilities."""

def select_events(events, tenant, status=None):
    """Return matching events without mutating the input."""
    return [e for e in events if e.tenant == tenant and (status is None or e.status == status)]



def event_latency_total(rows):
    """Sum latency values in reporting dictionaries."""
    return sum(row.get("latency", 0) for row in rows)


def event_latency_mean(rows):
    """Mean latency, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_latency_total(rows) / len(rows) if rows else 0


def event_latency_above(rows, threshold):
    """Select report dictionaries above a latency threshold."""
    return [row for row in rows if row.get("latency", 0) > threshold]


def event_latency_range(rows):
    """Return the minimum and maximum latency, or zeros."""
    values = [row.get("latency", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_attempts_total(rows):
    """Sum attempts values in reporting dictionaries."""
    return sum(row.get("attempts", 0) for row in rows)


def event_attempts_mean(rows):
    """Mean attempts, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_attempts_total(rows) / len(rows) if rows else 0


def event_attempts_above(rows, threshold):
    """Select report dictionaries above a attempts threshold."""
    return [row for row in rows if row.get("attempts", 0) > threshold]


def event_attempts_range(rows):
    """Return the minimum and maximum attempts, or zeros."""
    values = [row.get("attempts", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_size_total(rows):
    """Sum size values in reporting dictionaries."""
    return sum(row.get("size", 0) for row in rows)


def event_size_mean(rows):
    """Mean size, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_size_total(rows) / len(rows) if rows else 0


def event_size_above(rows, threshold):
    """Select report dictionaries above a size threshold."""
    return [row for row in rows if row.get("size", 0) > threshold]


def event_size_range(rows):
    """Return the minimum and maximum size, or zeros."""
    values = [row.get("size", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_duration_total(rows):
    """Sum duration values in reporting dictionaries."""
    return sum(row.get("duration", 0) for row in rows)


def event_duration_mean(rows):
    """Mean duration, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_duration_total(rows) / len(rows) if rows else 0


def event_duration_above(rows, threshold):
    """Select report dictionaries above a duration threshold."""
    return [row for row in rows if row.get("duration", 0) > threshold]


def event_duration_range(rows):
    """Return the minimum and maximum duration, or zeros."""
    values = [row.get("duration", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_retry_total(rows):
    """Sum retry values in reporting dictionaries."""
    return sum(row.get("retry", 0) for row in rows)


def event_retry_mean(rows):
    """Mean retry, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_retry_total(rows) / len(rows) if rows else 0


def event_retry_above(rows, threshold):
    """Select report dictionaries above a retry threshold."""
    return [row for row in rows if row.get("retry", 0) > threshold]


def event_retry_range(rows):
    """Return the minimum and maximum retry, or zeros."""
    values = [row.get("retry", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_count_total(rows):
    """Sum count values in reporting dictionaries."""
    return sum(row.get("count", 0) for row in rows)


def event_count_mean(rows):
    """Mean count, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_count_total(rows) / len(rows) if rows else 0


def event_count_above(rows, threshold):
    """Select report dictionaries above a count threshold."""
    return [row for row in rows if row.get("count", 0) > threshold]


def event_count_range(rows):
    """Return the minimum and maximum count, or zeros."""
    values = [row.get("count", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_priority_total(rows):
    """Sum priority values in reporting dictionaries."""
    return sum(row.get("priority", 0) for row in rows)


def event_priority_mean(rows):
    """Mean priority, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_priority_total(rows) / len(rows) if rows else 0


def event_priority_above(rows, threshold):
    """Select report dictionaries above a priority threshold."""
    return [row for row in rows if row.get("priority", 0) > threshold]


def event_priority_range(rows):
    """Return the minimum and maximum priority, or zeros."""
    values = [row.get("priority", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_sequence_total(rows):
    """Sum sequence values in reporting dictionaries."""
    return sum(row.get("sequence", 0) for row in rows)


def event_sequence_mean(rows):
    """Mean sequence, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_sequence_total(rows) / len(rows) if rows else 0


def event_sequence_above(rows, threshold):
    """Select report dictionaries above a sequence threshold."""
    return [row for row in rows if row.get("sequence", 0) > threshold]


def event_sequence_range(rows):
    """Return the minimum and maximum sequence, or zeros."""
    values = [row.get("sequence", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def order_events(events):
    """Newest first, ascending id for tied timestamps."""
    return sorted(events, key=lambda e: (e.created_at, -e.id), reverse=True)

def take_page(events, page, page_size):
    """Select a positive, one-based page."""
    if page <= 0 or page_size <= 0:
        raise ValueError("Page and page_size must be positive")
    start = (page - 1) * page_size
    return events[start:start + page_size]


def event_age_total(rows):
    """Sum age values in reporting dictionaries."""
    return sum(row.get("age", 0) for row in rows)


def event_age_mean(rows):
    """Mean age, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_age_total(rows) / len(rows) if rows else 0


def event_age_above(rows, threshold):
    """Select report dictionaries above a age threshold."""
    return [row for row in rows if row.get("age", 0) > threshold]


def event_age_range(rows):
    """Return the minimum and maximum age, or zeros."""
    values = [row.get("age", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_delay_total(rows):
    """Sum delay values in reporting dictionaries."""
    return sum(row.get("delay", 0) for row in rows)


def event_delay_mean(rows):
    """Mean delay, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_delay_total(rows) / len(rows) if rows else 0


def event_delay_above(rows, threshold):
    """Select report dictionaries above a delay threshold."""
    return [row for row in rows if row.get("delay", 0) > threshold]


def event_delay_range(rows):
    """Return the minimum and maximum delay, or zeros."""
    values = [row.get("delay", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_backlog_total(rows):
    """Sum backlog values in reporting dictionaries."""
    return sum(row.get("backlog", 0) for row in rows)


def event_backlog_mean(rows):
    """Mean backlog, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_backlog_total(rows) / len(rows) if rows else 0


def event_backlog_above(rows, threshold):
    """Select report dictionaries above a backlog threshold."""
    return [row for row in rows if row.get("backlog", 0) > threshold]


def event_backlog_range(rows):
    """Return the minimum and maximum backlog, or zeros."""
    values = [row.get("backlog", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)


def event_throughput_total(rows):
    """Sum throughput values in reporting dictionaries."""
    return sum(row.get("throughput", 0) for row in rows)


def event_throughput_mean(rows):
    """Mean throughput, defaulting to zero for an empty report."""
    rows = list(rows)
    return event_throughput_total(rows) / len(rows) if rows else 0


def event_throughput_above(rows, threshold):
    """Select report dictionaries above a throughput threshold."""
    return [row for row in rows if row.get("throughput", 0) > threshold]


def event_throughput_range(rows):
    """Return the minimum and maximum throughput, or zeros."""
    values = [row.get("throughput", 0) for row in rows]
    return (min(values), max(values)) if values else (0, 0)
