"""Saved appearance snapshot, injected into index.html so the first paint uses the chosen look.

Chromium's localStorage can lose recent writes when car power is cut; this copy is
written atomically and fsync'd by the service. Only CSS custom properties and simple
data attributes are accepted, and all of it is HTML-escaped when injected.
"""
import html
import json
import re

from .driving import atomic_write

DECLARATION = re.compile(r'--[a-z0-9-]{1,40}\s*:[^;<>\\{}]{0,300}')
NAME = re.compile(r'[a-zA-Z]{1,30}')
VALUE = re.compile(r'[\w-]{1,40}')
HTML_TAG = '<html lang="en">'


def validate(body):
    if not isinstance(body, dict) or set(body) != {'style', 'data', 'splash'}:
        raise ValueError('Expected style, data and splash')
    style, data, splash = body['style'], body['data'], body['splash']
    if not isinstance(style, str) or len(style) > 20000 or type(splash) is not bool:
        raise ValueError('Invalid style or splash')
    declarations = [part.strip() for part in style.split(';') if part.strip()]
    for part in declarations:
        lowered = part.lower()
        if not DECLARATION.fullmatch(part) or 'url(' in lowered or 'expression' in lowered or 'javascript' in lowered:
            raise ValueError('Only plain CSS custom properties are allowed')
    if not isinstance(data, dict) or len(data) > 16:
        raise ValueError('Invalid data attributes')
    clean = {}
    for name, value in data.items():
        if value is None:
            continue
        if not NAME.fullmatch(name) or not isinstance(value, str) or not VALUE.fullmatch(value):
            raise ValueError('Invalid data attribute')
        clean[name] = value
    return {'style': '; '.join(declarations), 'data': clean, 'splash': splash}


def attribute_name(name):
    return 'data-' + re.sub(r'([A-Z])', lambda m: '-' + m.group(1).lower(), name)


class Paint:
    def __init__(self, path):
        self.path = path
        self.value = None
        try:
            self.value = validate(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            pass  # No snapshot yet, or an unreadable one: the page applies the look itself.

    def save(self, value):
        atomic_write(self.path, value)
        self.value = value

    def inject(self, page):
        if not self.value:
            return page
        attrs = f' style="{html.escape(self.value["style"], quote=True)}"'
        attrs += ''.join(f' {attribute_name(k)}="{html.escape(v, quote=True)}"' for k, v in self.value['data'].items())
        if self.value['splash']:
            attrs += ' data-splash-pending="true"'
        return page.replace(HTML_TAG, HTML_TAG[:-1] + attrs + '>', 1)
