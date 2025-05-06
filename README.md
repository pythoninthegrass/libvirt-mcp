# libvirt-mcp
This is an experimental mcp server for libvirt. To try it, we use mcp-cli. The
following lines explain how to use it with ollama.
First, install mcp-cli:
```bash
git clone https://github.com/chrishayuk/mcp-cli
pip3.11 install -e ".[cli,dev]"
```
Then, install ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve >/dev/null 2>&1  &
ollama pull granite3.2:8b-instruct-q8_0
```
You need also `uv`:
```bash
pip install uv
```
You need the following python bindings:
```bash
dnf install libvirt-devel python3-devel
```
Then, in the libvirt-mcp directory, edit `server_config.json` and set up the
correct path to the libvirt-mcp server. Then, execute `run.sh`, which `ollama`
as provider and granite as model.

For debugging, you can install mcp:
```bash
dnf install -y npm
pip install mcp
```
And then, run:
```bash
mcp dev main.py
```
