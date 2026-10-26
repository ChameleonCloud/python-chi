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

"""An interactive shell in a container, shown in a notebook cell."""

import codecs
import threading

import anywidget
from zunclient.common.websocketclient.k8s_exec import SessionError

from chi.clients import zun

# Shows the shell with xterm.js, and passes keys and the terminal size to the
# kernel.
_ESM = """
import { Terminal } from "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/+esm";
import { FitAddon } from "https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/+esm";

function render({ model, el }) {
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css";
  const box = document.createElement("div");
  box.style.height = "24em";
  el.append(css, box);

  const term = new Terminal();
  const fit = new FitAddon();
  term.loadAddon(fit);
  term.open(box);

  const onMsg = (msg) => term.write(msg.out);
  model.on("msg:custom", onMsg);
  term.onData((data) => model.send({ in: data }));
  term.onResize(({ rows, cols }) => model.send({ rows, cols }));
  const resize = new ResizeObserver(() => fit.fit());
  resize.observe(box);
  fit.fit();
  model.send({ rows: term.rows, cols: term.cols });
  term.focus();

  return () => { model.off("msg:custom", onMsg); resize.disconnect(); term.dispose(); };
}

export default { render };
"""


class Console(anywidget.AnyWidget):
    """A shell in a container, shown in a notebook cell."""

    _esm = _ESM

    def __init__(self, container_id, command="sh"):
        super().__init__()
        self._session = zun().containers.execute_interactive(container_id, command)
        self.on_msg(self._from_browser)
        threading.Thread(target=self._to_browser, daemon=True).start()

    def close(self):
        """End the shell and remove the widget."""
        self._session.close()
        super().close()

    def _from_browser(self, _, msg, buffers):
        if "in" in msg:
            self._session.send(msg["in"].encode())
        elif "rows" in msg:
            self._session.resize(msg["cols"], msg["rows"])

    def _to_browser(self):
        decode = codecs.getincrementaldecoder("utf-8")("replace").decode
        try:
            while True:
                message = self._session.recv()
                if message is None:
                    break
                self.send({"out": decode(message[1])})
            end = f"exited with status {self._session.exit_code}"
        except SessionError as e:
            end = str(e)
        finally:
            self._session.close()
        self.send({"out": f"\r\n[{end}]\r\n"})
