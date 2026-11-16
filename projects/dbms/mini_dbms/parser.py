"""Parser for the intentionally small INSERT/SELECT SQL subset."""
from dataclasses import dataclass
import re

class SQLParseError(ValueError): pass

@dataclass(frozen=True)
class Statement:
    kind: str
    table: str
    columns: tuple = ()
    values: tuple = ()
    where: tuple | None = None

_TOKEN = re.compile(r"\s*(?:(-?\d+)|('(?:''|[^'])*')|([A-Za-z_][A-Za-z0-9_]*)|(\*)|(,)|(\()|(\))|(=)|(\?))")

def _tokens(sql):
    result, pos = [], 0
    while pos < len(sql):
        if sql[pos:].strip() == "": break
        m = _TOKEN.match(sql, pos)
        if not m: raise SQLParseError(f"Unexpected SQL near: {sql[pos:pos+24]!r}")
        number, quoted, word, star, comma, left, right, equals, param = m.groups()
        if number is not None: result.append(("value", int(number)))
        elif quoted is not None: result.append(("value", quoted[1:-1].replace("''", "'")))
        elif word is not None: result.append(("word", word.lower()))
        else:
            result.append(("*", None) if star else (",", None) if comma else ("(", None) if left else (")", None) if right else ("=", None) if equals else ("?", None))
        pos = m.end()
    return result

class _Parser:
    def __init__(self, sql, params): self.t, self.i, self.params, self.pi = _tokens(sql), 0, tuple(params), 0
    def take(self, kind=None, value=None):
        if self.i >= len(self.t): raise SQLParseError("Unexpected end of SQL")
        token = self.t[self.i]
        if kind is not None and token[0] != kind: raise SQLParseError(f"Expected {kind}, got {token[0]}")
        if value is not None and token[1] != value: raise SQLParseError(f"Expected {value}, got {token[1]}")
        self.i += 1; return token
    def kw(self, word): self.take("word", word)
    def name(self): return self.take("word")[1]
    def value(self):
        token = self.take()
        if token[0] == "value": return token[1]
        if token[0] == "?":
            if self.pi >= len(self.params): raise SQLParseError("Not enough parameters")
            value = self.params[self.pi]; self.pi += 1; return value
        raise SQLParseError("Expected a literal or ? parameter")
    def end(self):
        if self.i != len(self.t): raise SQLParseError("Unexpected trailing SQL")
        if self.pi != len(self.params): raise SQLParseError("Too many parameters")
    def statement(self):
        if not self.t: raise SQLParseError("Empty SQL statement")
        first = self.take("word")[1]
        if first == "insert":
            self.kw("into"); table = self.name(); self.take("("); cols = [self.name()]
            while self.i < len(self.t) and self.t[self.i][0] == ",": self.take(","); cols.append(self.name())
            self.take(")"); self.kw("values"); self.take("("); vals = [self.value()]
            while self.i < len(self.t) and self.t[self.i][0] == ",": self.take(","); vals.append(self.value())
            self.take(")"); self.end()
            return Statement("insert", table, tuple(cols), tuple(vals))
        if first == "select":
            if self.i < len(self.t) and self.t[self.i][0] == "*": self.take("*"); cols = ("*",)
            else:
                cols = [self.name()]
                while self.i < len(self.t) and self.t[self.i][0] == ",": self.take(","); cols.append(self.name())
                cols = tuple(cols)
            self.kw("from"); table = self.name(); where = None
            if self.i < len(self.t): self.kw("where"); column = self.name(); self.take("="); where = (column, self.value())
            self.end(); return Statement("select", table, tuple(cols), where=where)
        raise SQLParseError("Only INSERT and SELECT are supported")

def parse(sql, params=()):
    if not isinstance(sql, str): raise SQLParseError("SQL must be text")
    sql = sql.strip()
    if sql.endswith(";"): sql = sql[:-1].rstrip()
    if ";" in sql: raise SQLParseError("Only one statement is accepted")
    return _Parser(sql, params).statement()

def split_script(text):
    parts, start, quoted, i = [], 0, False, 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if quoted and i + 1 < len(text) and text[i+1] == "'": i += 2; continue
            quoted = not quoted
        elif ch == ";" and not quoted:
            part = text[start:i].strip()
            if part: parts.append(part)
            start = i + 1
        i += 1
    if quoted: raise SQLParseError("Unterminated string literal")
    tail = text[start:].strip()
    if tail: parts.append(tail)
    return parts
