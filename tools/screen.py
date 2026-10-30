# Reading a Claude Code pane from its captured text: the input box (typed text versus the dim suggestion), whether a
# menu, dialog or choice window holds the screen. Pure functions over `tmux capture-pane -e -p` output — probes feed
# them fixture screens. The UI marks are English strings of Claude Code 2.1.312; a probe pins them, so an update that
# changes them goes red. Idea and the dim/cursor handling after the remote-session module of another project.
import re

PROMPT_MARK = '❯'
RULER = '─'
# footers of dialogs and other views over the input box: a menu ❯ there is a picked item and Enter confirms it
DIALOG_MARKS = ('enter to confirm', 'esc to cancel', 'esc to go back', 'enter to return', 'space to reply',
                'ctrl+x to delete', '(y/n)', 'do you want to', 'background this session')
# a long paste is shown collapsed: «[Pasted text #2 +14 lines]»
PASTED = re.compile(r'\[\s*pasted\s+(?:text|content)\s*(?:#\d+)?\s*(?:\+\s*\d+\s*(?:lines?|chars?|characters?))?\s*\]', re.I)
UI_LINES = 6  # dialog footers live in the lowest lines of the pane
ESC = re.compile('\x1b(?:\\[([0-9;:?]*)([@-~])|\\][^\x07\x1b]*(?:\x07|\x1b\\\\)|[@-Z\\\\-_])')


def plain(screen):
    return ESC.sub('', screen)


def _sgr(params, dim, inverse):
    """Dim (SGR 2) and inverse (SGR 7) after ESC[…m; the 2 and 5 inside 38/48/58 colours are not attributes."""
    ps, i = (re.split('[;:]', params) if params else ['0']), 0
    while i < len(ps):
        v = int(ps[i]) if ps[i].isdigit() else 0
        if v in (38, 48, 58):
            nxt = ps[i + 1] if i + 1 < len(ps) else ''
            i += 3 if nxt == '5' else 5 if nxt == '2' else 1
            continue
        if v == 0:
            dim = inverse = False
        elif v == 22:
            dim = False
        elif v == 27:
            inverse = False
        elif v == 2:
            dim = True
        elif v == 7:
            inverse = True
        i += 1
    return dim, inverse


def split_dim(line):
    """A captured line → (normal text, dim text). The cursor is an inverse cell on the first letter of the dim
    suggestion: one such cell next to dim text counts as dim."""
    segs, dim, inverse, pos = [], False, False, 0
    for m in ESC.finditer(line):
        segs.append([line[pos:m.start()], dim, inverse])
        if m.group(2) == 'm':
            dim, inverse = _sgr(m.group(1), dim, inverse)
        pos = m.end()
    segs.append([line[pos:], dim, inverse])
    segs = [s for s in segs if s[0]]
    for i, (text, d, inv) in enumerate(segs):
        if inv and not d and len(text.strip()) <= 1:
            if any(segs[k][1] and segs[k][0].strip() for k in (i - 1, i + 1) if 0 <= k < len(segs)):
                segs[i][1] = True
    return ''.join(t for t, d, _ in segs if not d), ''.join(t for t, d, _ in segs if d)


def _ruler(text):
    return text.strip().startswith(RULER * 3)


def _box(lines):
    """(start, end) of the input box in split lines: the last «❯» line (not a menu item «❯ 1.») right under a ruler,
    down to the next ruler; none → None."""
    start = max((i for i, (text, _) in enumerate(lines)
                 if text.lstrip().startswith(PROMPT_MARK) and not re.match(r'\s*❯\s*\d+\.', text)
                 and i and _ruler(lines[i - 1][0])), default = None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if _ruler(lines[j][0])), None)
    return None if end is None else (start, end)


def input_box(screen):
    """The input box → (typed text, dim text); no box on the screen → None."""
    lines = [split_dim(line) for line in screen.rstrip('\n').split('\n')]
    box = _box(lines)
    if box is None:
        return None
    typed, faint = [], []
    for j in range(*box):
        text, dim = lines[j]
        typed.append((text.strip()[1:] if j == box[0] else text).replace('\u00a0', ' ').strip())
        faint.append(dim.strip())
    return ' '.join(t for t in typed if t), ' '.join(f for f in faint if f)


def _has_foreign_letter(text):
    """A footer is Claude Code's English UI: its symbols (·, ↑, ⏎) are not letters, so a non-ASCII letter means prose."""
    return any(c.isalpha() and ord(c) > 127 for c in text)


def dialog(screen):
    """A dialog footer in the lowest English UI lines — below the input box when there is one (an agent's text
    above it, or prose quoting a footer, does not count) → the mark; none → None."""
    lines = [split_dim(line) for line in screen.rstrip('\n').split('\n')]
    box = _box(lines)
    lines = [text for text, dim in lines[box[1] + 1 if box else 0:] if (text + dim).strip()][-UI_LINES:]
    for text in lines:
        text = text.strip()
        if len(text) <= 110 and not _has_foreign_letter(text):
            mark = next((m for m in DIALOG_MARKS if m in text.lower()), None)
            if mark:
                return mark
    return None


def norm(text):
    return re.sub(r'\s+', '', text or '').replace('…', '...')


def ours(box, text):
    """What the box shows is our text: collapsed paste, or start, middle and end of the visible part are in it."""
    if PASTED.search(box or ''):
        return True
    b, t = norm(box), norm(text)
    if not b:
        return False
    if len(b) <= 16:
        return b in t
    parts = (b[:16], b[len(b) // 2 - 8:len(b) // 2 + 8], b[-16:])
    return sum(p in t for p in parts) >= 2
