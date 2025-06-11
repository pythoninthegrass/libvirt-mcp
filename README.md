# libvirt-mcp
This is an experimental mcp server for libvirt. The
following lines explain how to use it with mcp-cli and ollama.
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
dnf install -y libvirt-devel python3-devel
```
Then, in the `libvirt-mcp` directory, first install the dependencies by running:
```bash
uv sync
```
Then, edit `server_config.json` and set up the correct path to the libvirt-mcp
server. Finally, execute `run.sh`, that uses `ollama` as provider and `granite`
as model.

![Demo](https://github.com/MatiasVara/libvirt-mcp/wiki/images/libvirt-mcp-demo-claude.gif)

For debugging, you can install mcp:
```bash
dnf install -y npm
pip install mcp
```
And then, run:
```bash
mcp dev setup.py
```
