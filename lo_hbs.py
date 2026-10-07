"""The small part of Handlebars the email templates use, so the site renders exactly the files it hands over.

The email files in emails/ are written for SendGrid dynamic templates (Handlebars). The site sends some of them
itself, so it renders the same text here instead of keeping a second copy in Jinja. Supported, and nothing else:

  {{name}} {{a.b}}        value, HTML-escaped          {{{name}}}         value, not escaped
  {{#if x}}..{{else}}..{{/if}}                         {{#unless x}}..{{/unless}}
  {{#each list}}..{{/each}}  (inside: {{this}}, {{field}}, {{../field}}, {{@root.field}}, {{@index}})

As in Handlebars, a name inside {{#each}} is looked up on the current item only; reach outside with ../ or @root.
"""
from __future__ import annotations

import html
import re
from typing import Any

_TOKEN = re.compile(r"\{\{\{\s*(.+?)\s*\}\}\}|\{\{\s*(.+?)\s*\}\}", re.S)


class TemplateError(ValueError):
    pass


def _parse(src: str) -> list:
    """-> nodes: str | ("var", path, raw) | ("block", kind, path, body, else_body)"""
    root: list = []
    stack: list[tuple[str, str, list, list | None]] = []   # kind, path, body, else_body
    out = root
    pos = 0
    for m in _TOKEN.finditer(src):
        if m.start() > pos:
            out.append(src[pos:m.start()])
        pos = m.end()
        if m.group(1) is not None:
            out.append(("var", m.group(1).strip(), True))
            continue
        tag = m.group(2).strip()
        if tag.startswith("!"):
            continue
        if tag.startswith("#"):
            kind, _, path = tag[1:].partition(" ")
            if kind not in ("if", "unless", "each"):
                raise TemplateError(f"unsupported block {{{{#{kind}}}}}")
            body: list = []
            stack.append((kind, path.strip(), body, None))
            out = body
        elif tag == "else":
            if not stack:
                raise TemplateError("{{else}} outside a block")
            kind, path, body, _ = stack[-1]
            else_body: list = []
            stack[-1] = (kind, path, body, else_body)
            out = else_body
        elif tag.startswith("/"):
            if not stack or stack[-1][0] != tag[1:].strip():
                raise TemplateError(f"unexpected {{{{{tag}}}}}")
            kind, path, body, else_body = stack.pop()
            parent = stack[-1][3] if stack and stack[-1][3] is not None else (stack[-1][2] if stack else root)
            parent.append(("block", kind, path, body, else_body or []))
            out = parent
        else:
            out.append(("var", tag, False))
    if stack:
        raise TemplateError(f"unclosed {{{{#{stack[-1][0]}}}}}")
    if pos < len(src):
        out.append(src[pos:])
    return root


def _lookup(path: str, scopes: list, index: int | None) -> Any:
    if path == "@index":
        return index
    if path.startswith("@root."):
        cur, path = scopes[0], path[6:]
    else:
        depth = 0
        while path.startswith("../"):
            depth, path = depth + 1, path[3:]
        cur = scopes[max(0, len(scopes) - 1 - depth)]
    if path in ("this", "."):
        return cur
    if path.startswith("this."):
        path = path[5:]
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _render(nodes: list, scopes: list, index: int | None) -> str:
    parts: list[str] = []
    for n in nodes:
        if isinstance(n, str):
            parts.append(n)
        elif n[0] == "var":
            v = _lookup(n[1], scopes, index)
            s = "" if v is None or v is False else str(v)
            parts.append(s if n[2] else html.escape(s, quote=True))
        else:
            _, kind, path, body, else_body = n
            v = _lookup(path, scopes, index)
            if kind == "each":
                items = list(v.items()) if isinstance(v, dict) else list(v or [])
                if not items:
                    parts.append(_render(else_body, scopes, index))
                for i, item in enumerate(items):
                    parts.append(_render(body, scopes + [item], i))
            else:
                truthy = bool(v) if not isinstance(v, (int, float)) or isinstance(v, bool) else v != 0
                if kind == "unless":
                    truthy = not truthy
                parts.append(_render(body if truthy else else_body, scopes, index))
    return "".join(parts)


def render(src: str, data: dict) -> str:
    return _render(_parse(src), [data or {}], None)


def variables(src: str) -> set[str]:
    """Top-level names a template reads (for the handover list)."""
    names: set[str] = set()

    def walk(nodes: list, inside_each: bool) -> None:
        for n in nodes:
            if isinstance(n, str):
                continue
            path = n[1] if n[0] == "var" else n[2]
            if path.startswith("@root."):
                names.add(path[6:].split(".")[0])
            elif not inside_each and not path.startswith(("../", "@", "this")):
                names.add(path.split(".")[0])
            if n[0] == "block":
                walk(n[3], inside_each or n[1] == "each")
                walk(n[4], inside_each or n[1] == "each")
    walk(_parse(src), False)
    return names
