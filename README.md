# libvirt-mcp

This is an experimental mcp server for libvirt. 

## Minimum Requirements

* [python 3.12+](https://www.python.org/downloads/)
* `ollama`:

    ```bash
    curl -fsSL https://ollama.com/install.sh | sh
    ollama serve >/dev/null 2>&1  &
    ollama pull granite3.2:8b-instruct-q8_0
    ```

* `uv`:

    ```bash
    python -m pip install uv
    ```

* python bindings:

    ```bash
    # ubuntu/debian
    sudo apt update
    sudo apt install -y libvirt-dev python3-dev

    # alma/fedora/rhel
    dnf install -y libvirt-devel python3-devel

    # macos
    brew install libvirt
    ```

## Setup

The following lines explain how to use it with `mcp-cli` and `ollama`.

First, install `mcp-cli`:

```bash
# uvx
uvx mcp-cli --help

# source
git clone https://github.com/chrishayuk/mcp-cli
python -m pip install -e ".[cli,dev]"
```

Then, in the `libvirt-mcp` directory, first install the dependencies by running:

```bash
uv sync
```

### Configuration

1. Copy the example environment file and customize it:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` to configure your preferred LLM provider and model:
   ```bash
   LLM_PROVIDER=ollama
   LLM_MODEL=granite3.2:8b-instruct-q8_0
   OLLAMA_API_BASE=http://localhost:11434
   ```

3. Edit `server_config.json` and set up the correct path to the libvirt-mcp server.

4. Execute `run.sh`, which will use your configured provider and model:
   ```bash
   ./run.sh
   ```

<!-- ## Demo -->

<!-- ![Demo](https://github.com/MatiasVara/libvirt-mcp/wiki/images/libvirt-mcp-demo-claude.gif) -->

## Troubleshooting

For debugging, you can install mcp:

```bash
# ubuntu/debian
sudo apt install -y nodejs npm

# alma/fedora/rhel
sudo dnf install -y npm

# mcp library
python -m pip install mcp
```

And then, run:

```bash
mcp dev setup.py
```

## TODO

See [TODO.md](TODO.md) for pending tasks.
