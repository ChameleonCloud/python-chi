# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A terminal in a notebook cell, running a command in a container."""

import threading

import anywidget
import traitlets
from zunclient import exceptions

from .clients import zun

# xterm.js in the cell. Keys and terminal size go to the kernel as widget
# messages; the command's output comes back the same way, as bytes.
_ESM = """
import { Terminal } from "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/+esm";
import { FitAddon } from "https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/+esm";

const CSS = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css";

function bytes(view) {
  return new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
}

function render({ model, el }) {
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = CSS;
  const box = document.createElement("div");
  box.style.height = model.get("height");
  el.append(css, box);

  const term = new Terminal();
  const fit = new FitAddon();
  term.loadAddon(fit);
  term.open(box);

  model.on("msg:custom", (msg, buffers) => {
    if (msg.type === "output") {
      term.write(bytes(buffers[0]));
    } else if (msg.type === "exit") {
      term.write(`\\r\\n[${msg.reason}]\\r\\n`);
    }
  });
  term.onData((data) => model.send({ type: "input", data }));
  term.onResize(({ cols, rows }) => model.send({ type: "resize", cols, rows }));
  // Start the command once the cell is laid out, so that it starts with
  // the terminal's real size rather than xterm's default 80x24.
  let ready = false;
  const resize = new ResizeObserver(() => {
    if (!box.clientWidth) return;
    fit.fit();
    if (!ready) {
      ready = true;
      model.send({ type: "ready", cols: term.cols, rows: term.rows });
    }
  });
  resize.observe(box);
  term.focus();

  return () => { resize.disconnect(); term.dispose(); };
}

export default { render };
"""


class Console(anywidget.AnyWidget):
    """A terminal running a command in a container, shown in a notebook cell.

    The command starts when the terminal first appears, and keeps running
    if the terminal is closed, as with docker exec -it.
    """

    _esm = _ESM
    height = traitlets.Unicode("24em").tag(sync=True)

    def __init__(self, container_id, command="sh", height="24em"):
        super().__init__()
        self._container_id = container_id
        self._command = command
        self._session = None
        self.height = height
        self.on_msg(self._on_msg)

    def _on_msg(self, widget, content, buffers):
        kind = content.get("type")
        try:
            if kind == "ready" and self._session is None:
                self._start(content["cols"], content["rows"])
            elif self._session is None:
                return
            elif kind == "input":
                self._session.send(content["data"].encode())
            elif kind == "resize":
                self._session.resize(content["cols"], content["rows"])
        except exceptions.Disconnected:
            pass  # the command has exited; _wait reports it

    def _start(self, cols, rows):
        self._session = zun().containers.execute_session(
            self._container_id,
            self._command,
            stdout=self._output,
            interactive=True,
            tty=True,
        )
        self._session.resize(cols, rows)
        threading.Thread(target=self._wait, daemon=True).start()

    def _output(self, data):
        self.send({"type": "output"}, buffers=[data])

    def _wait(self):
        try:
            reason = "exited with %d" % self._session.wait()
        except Exception as e:
            reason = "ended: %s" % e
        self.send({"type": "exit", "reason": reason})

    def close(self):
        """Close the terminal. The command keeps running if it hasn't exited."""
        if self._session is not None:
            self._session.close()
        super().close()
