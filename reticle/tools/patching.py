"""Strict single-file unified diffs, validated completely before the caller writes."""
import re


HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)")


def apply_unified_diff(raw: bytes, patch: str) -> bytes:
    source = raw.decode('utf-8').splitlines(keepends=True)
    rows = patch.replace('\r\n', '\n').split('\n')
    if rows and rows[-1] == '':
        rows.pop()
    index = 0
    if rows and rows[0].startswith('diff --git '):
        index = 1
        if index < len(rows) and rows[index].startswith('index '):
            index += 1
    if index < len(rows) and rows[index].startswith('--- '):
        if index + 1 >= len(rows) or not rows[index+1].startswith('+++ '):
            raise ValueError('expected +++ after --- header')
        index += 2
    output = []
    cursor = hunks = 0
    while index < len(rows):
        match = HUNK.fullmatch(rows[index])
        if not match:
            raise ValueError('expected unified diff @@ hunk header; only one file is supported')
        old_start, old_count, new_start, new_count = (
            int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
        position = old_start if old_count == 0 else old_start - 1
        if position < cursor or position > len(source):
            raise ValueError('hunk position is outside the file or overlaps a previous hunk')
        output.extend(source[cursor:position])
        expected_new = len(output) if new_count == 0 else len(output) + 1
        if new_start != expected_new:
            raise ValueError('new hunk position does not match preceding changes')
        cursor = position
        nearby = source[position:position+1] or source[max(0, position-1):position]
        ending = '\r\n' if nearby and nearby[0].endswith('\r\n') else '\n'
        consumed = produced = 0
        index += 1
        while index < len(rows) and not rows[index].startswith('@@ '):
            row = rows[index]
            if not row or row[0] not in ' +-':
                raise ValueError('hunk lines must begin with space, +, or -')
            kind, text = row[0], row[1:]
            no_newline = index + 1 < len(rows) and rows[index+1] == '\\ No newline at end of file'
            if kind in ' -':
                original = source[cursor] if cursor < len(source) else None
                if original is not None:
                    original = original[:-2] if original.endswith('\r\n') else original.removesuffix('\n')
                if original != text:
                    raise ValueError(f'hunk context does not match source line {cursor+1}; no change made')
                if no_newline and source[cursor].endswith('\n'):
                    raise ValueError('no-newline marker disagrees with source')
                consumed += 1
            if kind == ' ':
                output.append(source[cursor])
                produced += 1
            elif kind == '+':
                output.append(text + ('' if no_newline else ending))
                produced += 1
            if kind in ' -':
                cursor += 1
            index += 2 if no_newline else 1
        if consumed != old_count or produced != new_count:
            raise ValueError('hunk line counts do not match header; no change made')
        hunks += 1
    if not hunks:
        raise ValueError('patch must contain at least one @@ hunk')
    output.extend(source[cursor:])
    return ''.join(output).encode('utf-8')
