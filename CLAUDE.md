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
# Lint and format python code
ruff check
ruff format

# Run ruff with auto-fix
ruff check --fix

# Lint jinja2 templates
j2lint <directory_or_file>

# Preview jinja2 rendering
SSH_KEY=$(printf "ssh_authorized_keys:\n  - %s" "$(cat ~/.ssh/id_rsa.pub)")
jinja2 -D ssh_keys_section="$SSH_KEY" -D username="ubuntu" --format=env templates/cloud-init.yml.j2
```

### Markdown Editing Guidelines

- When editing markdown files, always follow `markdownlint -c .markdownlint.jsonc <markdown_file>` linting rules.

### Testing

#### Quick Test Commands

```bash
# Run all tests (recommended)
uv run tests/run_tests.py

# Run all tests with pytest
pytest

# Run tests in parallel
pytest -n auto

# Run specific test file
uv run tests/test_handlers.py
pytest tests/test_handlers.py
```

#### Test Categories

```bash
# Run all tests by category
uv run tests/test_handlers.py        # Core utility functions
uv run tests/test_image_access.py    # Image access and resolution
uv run tests/test_vm_operations.py   # VM operations and libvirt
uv run tests/test_mcp_tools.py       # MCP tools and business logic

# Run tests with pytest markers
pytest -m unit                      # Unit tests
pytest -m integration              # Integration tests  
pytest -m e2e                      # End-to-end tests
pytest -m benchmark                # Performance tests
```

#### Test Configuration

```bash
# Test with different libvirt connections
LIBVIRT_DEFAULT_URI=qemu:///system pytest                    # Local
LIBVIRT_DEFAULT_URI=qemu+ssh://user@host/system pytest       # Remote SSH

# Test with coverage
pytest --cov=handlers --cov-report=html

# Test with detailed output
pytest -v -s
```

#### Test Development

```bash
# Install test dependencies
uv sync --group test

# Run specific test function
pytest tests/test_handlers.py::test_url_detection

# Run failed tests only
pytest --lf

# Run tests matching pattern
pytest -k "test_url"
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

## Pulumi commands

```bash
# Log into local pulumi
pulumi login file://~

# Set empty passphrase
PULUMI_CONFIG_PASSPHRASE=

# Create a new project
pulumi new python

# Create a new stack
pulumi stack init dev

# Configure the stack
pulumi config set vm_count 1

# Preview the changes
pulumi preview

# Apply the changes
pulumi up --yes

# Destroy the changes
pulumi destroy --yes

# Remove the stack
pulumi stack rm --yes

# Check stack output
pulumi stack output --json
```

**Note**: On macOS, use `./run-pulumi.sh` instead of `pulumi` directly. This script handles SSH agent setup required for remote libvirt connections.

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
- Configurable VM and image settings via environment variables:
  - `BASE_IMAGE_NAME`: Name of the base volume (default: "ubuntu-base-volume")
  - `BASE_IMAGE_PATH`: Absolute path to source image (default: "/data/libvirt/images/ubuntu-24.04-base.qcow2")
  - `VM_NAME_PREFIX`: Prefix for VM names (default: "ubuntu")
  - `STORAGE_POOL`: Storage pool name (default: "default")
  - `IMAGE_FORMAT`: Image format (default: "qcow2")

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
- Python 3.12+ requirement
- Ruff for linting/formatting with extensive rule set
- Import ordering and style consistency

**VM Creation Specifics**:

- Default to qcow2 disk format
- Standard image path: `/var/lib/libvirt/images/{name}.qcow2`
- Virtio network and disk drivers for performance
- Template XML definitions in handlers.py

The architecture prioritizes clean separation between MCP protocol handling and libvirt operations, making it easy to extend with new VM management tools while maintaining consistent error handling and resource management patterns.

## Debugging

```bash
# List all VMs (running and stopped)
virsh list --all

# If virsh by itself isn't working be explicit
LIBVIRT_DEFAULT_URI="qemu+ssh://user@libvirthost/system" virsh list --all

# Start all stopped VMs
virsh list --name --inactive | xargs -I {} virsh start {}

# Destroy all running VMs (forceful shutdown)
for vm in $(sudo virsh list --name); do sudo virsh destroy $vm; done

# Delete all VM definitions (remove configuration)
for vm in $(sudo virsh list --all --name); do sudo virsh undefine $vm; done

# Clean up VM disk images
sudo rm -f /var/lib/libvirt/images/*.qcow2

# Check AppArmor logs for potential issues
sudo dmesg | grep -i apparmor

# Whitelist libvirt images in AppArmor config
# * /etc/apparmor.d/abstractions/libvirt-qemu
/var/lib/libvirt/images-*/** rwk,

# iso permissions
sudo chown libvirt-qemu:libvirt-qemu /data/libvirt/images/ubuntu-jammy-base

# Fix libvirt images directory permissions for non-root users
sudo usermod -a -G libvirt ubuntu
# Verify group membership
groups ubuntu
# User needs to log out and back in or restart libvirt for group changes to take effect
sudo systemctl restart libvirtd

# Fix images directory permissions (if still getting permission denied)
sudo chgrp libvirt /var/lib/libvirt/images
sudo chmod g+rx /var/lib/libvirt/images

# Mount and inspect cloud-init ISO
ssh user@libvirthost "sudo virsh domblklist ubuntu-1"
ssh user@libvirthost "sudo mount -o loop /data/libvirt/images/cloudinit-1.iso /mnt && ls -la /mnt/" 
ssh user@libvirthost "sudo cat /mnt/user-data | base64 -d"

# Final troubleshooting step: Disable SELinux/AppArmor if all else fails
sudo setenforce 0               # Disable SELinux
sudo systemctl stop apparmor    # Stop AppArmor

# Start SSH agent and add key
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa

# Verify key is loaded
ssh-add -l

# Guestfish debugging commands for cloud-init logs
guestfish -a /path/to/disk.qcow2 -i                    # Open image
cat /var/log/cloud-init.log                           # View cloud-init logs
cat /var/log/cloud-init-output.log                    # View cloud-init output logs
virt-log -d <domain_name>                             # Show logs for specific VM
```

<!-- ! This section should always be located at the end of the markdown file -->
## Documentation References

- Use [context7](https://context7.com/libvirt/libvirt/llms.txt) as the primary source
- libvirt-python: <https://github.com/libvirt/libvirt-python>
- python xml api bindings: <https://libvirt.org/python.html>
- xml format: <https://libvirt.org/format.html>
- cloud-init implementation: <https://github.com/gergelykalman/libvirt-cloudinit-autoinstaller>
- terraform libvirt provider: <https://registry.terraform.io/providers/dmacvicar/libvirt/latest/docs>
- pulumi libvirt provider: <https://www.pulumi.com/registry/packages/libvirt/>
- vagrant libvirt provider: <https://context7.com/vagrant-libvirt/vagrant-libvirt/llms.txt>
- mcp-cli: <https://github.com/chrishayuk/mcp-cli>
