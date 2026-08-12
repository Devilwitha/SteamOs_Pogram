"""Minimaler Parser fuer das Valve Data Format (VDF), wie es Steam fuer
'libraryfolders.vdf' und 'appmanifest_*.acf' Dateien verwendet.

Unterstuetzt nur das, was in diesen Dateien tatsaechlich vorkommt:
verschachtelte, in Anfuehrungszeichen gesetzte Schluessel/Werte-Paare in
geschweiften Klammern sowie '//'-Kommentare.
"""


def loads(text):
    tokens = _tokenize(text)
    pos = 0

    def parse_object():
        nonlocal pos
        obj = {}
        while pos < len(tokens):
            token = tokens[pos]
            if token == "}":
                pos += 1
                return obj
            key = token
            pos += 1
            if pos >= len(tokens):
                break
            value_token = tokens[pos]
            if value_token == "{":
                pos += 1
                obj[key] = parse_object()
            else:
                obj[key] = value_token
                pos += 1
        return obj

    return parse_object()


def _tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "{" or c == "}":
            tokens.append(c)
            i += 1
            continue
        if c == '"':
            i += 1
            value = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    value.append(text[i + 1])
                    i += 2
                else:
                    value.append(text[i])
                    i += 1
            tokens.append("".join(value))
            i += 1
            continue
        i += 1
    return tokens


def load(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return loads(f.read())
