# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Setup and Dependencies

```bash
# Install dependencies
uv sync

# Install with development dependencies
uv sync --group dev

# Install with test dependencies  
uv sync --group test
```

### Code Quality

```bash
# Lint and format code
ruff check
ruff format

# Run with auto-fix
ruff check --fix
```

### Testing

```bash
# Run all tests
pytest

# Run specific test types
pytest -m unit
pytest -m integration
pytest -m e2e

# Run with parallel execution
pytest -n auto

# Run single test file
pytest tests/test_specific.py
```

### Running the MCP Server

```bash
# Start the complete demo environment
./run.sh

# Test MCP server directly
uv run server.py

# Debug mode with mcp tools
mcp dev server.py
```

## Development Best Practices

- Always use `uv run` to activate the virtual environment for one-off commands

## Architecture Overview

### Core Structure

- **server.py**: Minimal MCP server entry point using FastMCP
- **handlers.py**: All MCP tools and resources implementation
- **run.sh**: Complete environment setup with ollama and mcp-cli

### MCP Server Design

The project implements a Model Context Protocol (MCP) server that bridges AI models with libvirt virtualization:

- **Resources**: Template-based URIs for OS image paths (`images://{os_name}`)
- **Tools**: VM management operations (create, destroy, list, get_ip, shutdown)
- **Transport**: stdio-based communication for MCP client integration

### Key Components

**LibVirt Integration**:

- Uses `LIBVIRT_DEFAULT_URI` environment variable (defaults to "qemu:///system")
- XML-based VM definitions with parameterized templates
- Network integration through DHCP lease parsing
- Error handling for all libvirt operations

**VM Management Pattern**:

- Template-driven VM creation with virtio drivers
- MAC address assignment and network configuration
- Resource specification (CPU cores, memory, disk paths)
- Complete lifecycle management (create → list → shutdown → destroy)

**Environment Configuration**:

- Uses `python-decouple` for environment variable management
- `.env` file support for local overrides
- MCP-CLI integration with LLM provider settings

### File Structure Context

- `server_config.json`: MCP server connection configuration
- `.env.example`: Template for environment variables
- `pyproject.toml`: Project dependencies and tool configuration (ruff, pytest)

### Development Notes

**Testing Strategy**:

- Markers for test categorization (unit, integration, e2e, benchmark)
- Async test support with pytest-asyncio
- Property-based testing with hypothesis

**Code Standards**:

- Line length: 130 characters
- Python 3.11+ requirement
- Ruff for linting/formatting with extensive rule set
- Import ordering and style consistency

**VM Creation Specifics**:

- Default to qcow2 disk format
- Standard image path: `/var/lib/libvirt/images/{name}.qcow2`
- Virtio network and disk drivers for performance
- Template XML definitions in handlers.py

The architecture prioritizes clean separation between MCP protocol handling and libvirt operations, making it easy to extend with new VM management tools while maintaining consistent error handling and resource management patterns.

## Markdown Editing Guidelines

- When editing markdown files, always follow `markdownlint -c .markdownlint.jsonc <markdown_file>` linting rules.

## Debugging

- list vms: `virsh list --all`
- start all stopped vms:

    ```bash
    for vm in $(virsh list --name --inactive); do
        virsh start "$vm"
    done
    ```

- check apparmor: `sudo dmesg | grep -i apparmor`
- whitelist libvirt images

    ```bash
    # /etc/apparmor.d/abstractions/libvirt-qemu
    /var/lib/libvirt/images-*/** rwk,
    ```

## Documentation References

- Use [context7](https://context7.com/libvirt/libvirt/llms.txt) as the primary source
- python xml api bindings: <https://libvirt.org/python.html>
- xml format: <https://libvirt.org/format.html>
- terraform libvirt provider: <https://registry.terraform.io/providers/dmacvicar/libvirt/latest/docs>
- pulumi libvirt provider: <https://www.pulumi.com/registry/packages/libvirt/>
- vagrant libvirt provider: <https://context7.com/vagrant-libvirt/vagrant-libvirt/llms.txt>
- mcp-cli: <https://github.com/chrishayuk/mcp-cli>
