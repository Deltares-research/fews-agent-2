"""Incremental extraction of the ``"reply"`` string from a streaming JSON.

The turn's model response is one JSON object ``{"reply": "...", "patch":
[...]}`` — streaming it raw would show the user braces and op names. This
scanner watches the token stream and yields ONLY the reply string's content,
unescaped, as it arrives; the full JSON still accumulates at the caller for
normal parsing when the stream ends.

Pure and incremental: ``feed(chunk) -> str`` returns whatever new reply text
this chunk completed. Handles the reply key appearing anywhere, chunk
boundaries splitting escapes, and ``\\uXXXX`` sequences.
"""
from __future__ import annotations

_KEY = '"reply"'


class ReplyStreamExtractor:
    def __init__(self) -> None:
        self._buf = ""          # everything seen so far
        self._pos = 0           # scan position
        self._state = "seek"    # seek -> colon -> quote -> in_string -> done

    def feed(self, chunk: str) -> str:
        self._buf += chunk or ""
        out: list[str] = []
        while self._pos < len(self._buf):
            if self._state == "seek":
                idx = self._buf.find(_KEY, self._pos)
                if idx == -1:
                    # keep enough tail to complete a split key next chunk
                    self._pos = max(self._pos, len(self._buf) - len(_KEY))
                    break
                self._pos = idx + len(_KEY)
                self._state = "colon"
            elif self._state == "colon":
                c = self._buf[self._pos]
                self._pos += 1
                if c == ":":
                    self._state = "quote"
                elif not c.isspace():
                    self._state = "seek"        # not actually the key slot
            elif self._state == "quote":
                c = self._buf[self._pos]
                self._pos += 1
                if c == '"':
                    self._state = "in_string"
                elif not c.isspace():
                    self._state = "seek"
            elif self._state == "in_string":
                c = self._buf[self._pos]
                if c == "\\":
                    if self._pos + 1 >= len(self._buf):
                        break                    # escape split across chunks
                    esc = self._buf[self._pos + 1]
                    if esc == "u":
                        if self._pos + 6 > len(self._buf):
                            break
                        try:
                            out.append(chr(int(
                                self._buf[self._pos + 2:self._pos + 6], 16)))
                        except ValueError:
                            pass
                        self._pos += 6
                    else:
                        out.append({"n": "\n", "t": "\t", "r": "\r",
                                    '"': '"', "\\": "\\", "/": "/"}.get(esc, esc))
                        self._pos += 2
                elif c == '"':
                    self._pos += 1
                    self._state = "done"
                else:
                    out.append(c)
                    self._pos += 1
            else:                                # done
                self._pos = len(self._buf)
        return "".join(out)
