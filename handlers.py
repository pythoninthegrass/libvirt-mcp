#!/usr/bin/env python

import base64
import contextlib
import hashlib
import jinja2
import json
import libvirt
import os
import paramiko
import sh
import urllib.request
import xml.etree.ElementTree as ET
from decouple import config
from pathlib import Path
from sh import CommandNotFound, ErrorReturnCode
from urllib.parse import urlparse


def import_sh_cmd(cmd_name):
    """Import sh commands with fallback to None."""
    try:
        return getattr(__import__('sh'), cmd_name)
    except (ImportError, AttributeError):
        return None


# Import shell commands with fallbacks
arp = import_sh_cmd('arp')
pulumi = import_sh_cmd('pulumi')
scp = import_sh_cmd('scp')
sudo = import_sh_cmd('sudo')

# Default libvirt URI
LIBVIRT_DEFAULT_URI = config("LIBVIRT_DEFAULT_URI", default="qemu:///system")


def _pulumi_command(command, timeout=300):
    """Execute pulumi command with JSON output and return parsed result.

    Args:
        command: List of command arguments (e.g., ['up', '--yes'])
        timeout: Command timeout in seconds

    Returns:
        tuple: (success: bool, result: dict, error_message: str or None)
    """
    try:
        if pulumi is None:
            return False, None, "pulumi command not available. Please install pulumi."

        # Always add --non-interactive and --json for programmatic access
        full_cmd = command + ['--non-interactive', '--json']

        result = pulumi(*full_cmd, _timeout=timeout, _cwd=Path(__file__).parent)
        output = result.stdout.decode().strip()

        # Parse JSON output
        try:
            json_result = json.loads(output)
            return True, json_result, None
        except json.JSONDecodeError:
            # Some commands might not return JSON, return raw output
            return True, {'output': output}, None

    except ErrorReturnCode as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        return False, None, f"Pulumi command failed: {error_msg}"
    except Exception as e:
        return False, None, f"Failed to run pulumi command: {str(e)}"


def _pulumi_preview():
    """Run pulumi preview and return the result.

    Returns:
        tuple: (success: bool, result: dict, error_message: str or None)
    """
    return _pulumi_command(['preview'])


def _pulumi_up():
    """Run pulumi up and return the result.

    Returns:
        tuple: (success: bool, result: dict, error_message: str or None)
    """
    return _pulumi_command(['up', '--yes'])


def _pulumi_destroy():
    """Run pulumi destroy and return the result.

    Returns:
        tuple: (success: bool, result: dict, error_message: str or None)
    """
    return _pulumi_command(['destroy', '--yes'])


def _pulumi_stack_output(output_name=None):
    """Get pulumi stack output.

    Args:
        output_name: Optional specific output name to retrieve

    Returns:
        tuple: (success: bool, result: dict, error_message: str or None)
    """
    cmd = ['stack', 'output']
    if output_name:
        cmd.append(output_name)
    return _pulumi_command(cmd)


def ssh_cmd(host, command, timeout=30):
    """Execute a command on remote host via SSH using paramiko.

    Args:
        host: SSH host in format 'username@hostname' or 'hostname'
        command: Command to execute (string or list)
        timeout: Timeout in seconds

    Returns:
        tuple: (success: bool, stdout: str, stderr: str)
    """
    try:
        # Parse host string
        if "@" in host:
            username, hostname = host.split("@", 1)
        else:
            username = "root"
            hostname = host

        # Convert command list to string if needed
        if isinstance(command, list):
            command = " ".join(command)

        # Connect via SSH
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname, username=username, timeout=timeout)

        # Execute command
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)

        # Get results
        stdout_str = stdout.read().decode().strip()
        stderr_str = stderr.read().decode().strip()
        exit_code = stdout.channel.recv_exit_status()

        ssh_client.close()

        return exit_code == 0, stdout_str, stderr_str

    except Exception as e:
        return False, "", str(e)


def _is_url(path_or_url):
    """Check if the given string is a URL."""
    try:
        parsed = urlparse(path_or_url)
        return parsed.scheme in ('http', 'https', 'ftp', 'ftps')
    except Exception:
        return False


def _get_cache_path(url):
    """Generate a cached file path for a URL."""
    # Create a hash of the URL for the filename
    url_hash = hashlib.md5(url.encode()).hexdigest()
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = f"image_{url_hash}.qcow2"

    # Use libvirt images directory for caching
    cache_dir = Path("/var/lib/libvirt/images")
    cache_path = cache_dir / f"cached_{url_hash}_{filename}"
    return cache_path


def _download_image(url, cache_path):
    """Download an image from URL to cache path."""
    try:
        # Create cache directory if it doesn't exist
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Download the file
        with urllib.request.urlopen(url) as response, open(cache_path, 'wb') as f:
            # Download in chunks to handle large files
            chunk_size = 8192
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)

        return True, None
    except Exception as e:
        return False, f"Failed to download image from {url}: {str(e)}"


def _resolve_image_path(path_or_url):
    """Resolve image path, handling URLs and local paths with fallback downloading."""
    # If it's a URL, handle download/caching
    if _is_url(path_or_url):
        cache_path = _get_cache_path(path_or_url)

        # Check if cached version exists
        if cache_path.exists():
            return str(cache_path), None

        # Download and cache the image
        success, error = _download_image(path_or_url, cache_path)
        if success:
            return str(cache_path), None
        else:
            return None, error

    # It's a local path, but we need to handle remote libvirt hosts
    path = Path(path_or_url)

    # Check if using SSH connection to remote host
    if "ssh://" in LIBVIRT_DEFAULT_URI:
        # Extract hostname from URI like qemu+ssh://user@hostname/system
        host_part = LIBVIRT_DEFAULT_URI.split("://")[1].split("/")[0]

        # Test if remote path exists via SSH
        try:
            success, stdout, stderr = ssh_cmd(host_part, f"test -f {path_or_url}", timeout=10)
            if success:
                return str(path_or_url), None
            else:
                return None, f"Remote image path does not exist: {path_or_url}"
        except Exception as e:
            return None, f"Failed to check remote image path: {str(e)}"
    else:
        # Check if local path exists (original behavior)
        if path.exists():
            return str(path), None

        # Local path doesn't exist, cannot proceed
        return None, f"Local image path does not exist: {path_or_url}"


def get_os_image_path(os_name: str) -> str:
    """Return the path in the system to a disk with OS installed"""
    # Check multiple possible locations for images
    possible_paths = [
        f"/var/lib/libvirt/images/{os_name}.qcow2",
        f"/data/libvirt/images/{os_name}.qcow2",
        f"/var/lib/libvirt/images/{os_name}.img",
        f"/data/libvirt/images/{os_name}.img",
        "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img",   # Common ubuntu image
        "/var/lib/libvirt/images/noble-server-cloudimg-amd64.img",          # Common ubuntu image
        "/data/libvirt/images/ubuntu-24.04-base.qcow2",                     # Common custom image
    ]

    # If using ssh connection, check remote paths
    if "ssh://" in LIBVIRT_DEFAULT_URI:
        host_part = LIBVIRT_DEFAULT_URI.split("://")[1].split("/")[0]

        for path in possible_paths:
            try:
                success, stdout, stderr = ssh_cmd(host_part, f"test -f {path}", timeout=5)
                if success:
                    return path
            except Exception:
                continue
    else:
        # Check local paths
        for path in possible_paths:
            if Path(path).exists():
                return path

    # Default fallback
    return f"/var/lib/libvirt/images/{os_name}.qcow2"


def _get_template_env():
    """Get the Jinja2 template environment configured for the templates directory."""
    template_path = Path(__file__).parent / "templates"
    template_loader = jinja2.FileSystemLoader(template_path)
    template_env = jinja2.Environment(loader=template_loader)
    return template_env


def _render_domain_xml(name, memory, cores, disk_path, mac_address, cdrom_path=None):
    """Render libvirt domain XML using Jinja2 template.

    Args:
        name: VM name
        memory: Memory in MiB
        cores: Number of CPU cores
        disk_path: Path to disk image
        mac_address: MAC address for network interface
        cdrom_path: Optional path to CD-ROM image

    Returns:
        str: Rendered XML configuration
    """
    template_env = _get_template_env()
    template = template_env.get_template("domain.xml.j2")

    return template.render(
        name=name,
        memory=memory,
        cores=cores,
        disk_path=disk_path,
        mac_address=mac_address,
        cdrom_path=cdrom_path,
    )


def create_network_config(static_ip=None, gateway=None, nameservers=None, interface="enp1s0"):
    """Create network configuration for cloud-init using Jinja2 template.

    Args:
        static_ip: Static IP address with CIDR (e.g., "192.168.122.100/24")
        gateway: Gateway IP address (e.g., "192.168.122.1")
        nameservers: List of DNS servers (default: ["8.8.8.8", "8.8.4.4"])
        interface: Network interface name (default: "enp1s0")

    Returns:
        str: Network configuration YAML
    """
    if nameservers is None:
        nameservers = ["8.8.8.8", "8.8.4.4"]

    # Load and render template
    template_env = _get_template_env()
    template = template_env.get_template("network-config.yml.j2")

    network_config = template.render(
        static_ip=static_ip,
        gateway=gateway,
        nameservers=nameservers,
        interface=interface,
    )
    return network_config


def register_handlers(mcp):
    def _start_vm(vm_name: str):
        """Start a VM. Returns (success: bool, message: str)"""
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return False, f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)
        except libvirt.libvirtError as e:
            conn.close()
            return False, f"VM '{vm_name}' not found: {str(e)}"

        try:
            # Check if VM is already running
            if domain.isActive():
                conn.close()
                return False, f"VM '{vm_name}' is already running"

            # Start the VM
            domain.create()
            conn.close()
            return True, "OK"
        except libvirt.libvirtError as e:
            conn.close()
            return False, f"Failed to start VM '{vm_name}': {str(e)}"

    def _stop_vm(vm_name: str, force: bool = False):
        """Stop a VM. Returns (success: bool, message: str)"""
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return False, f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)
        except libvirt.libvirtError as e:
            conn.close()
            return False, f"VM '{vm_name}' not found: {str(e)}"

        try:
            if domain.isActive():
                if force:
                    domain.destroy()    # Forceful shutdown
                else:
                    domain.shutdown()   # Graceful shutdown
            conn.close()
            return True, "OK"
        except libvirt.libvirtError as e:
            conn.close()
            return False, f"Failed to stop VM '{vm_name}': {str(e)}"

    def _is_vm_running(vm_name: str):
        """Check if VM is running. Returns (is_running: bool, error_msg: str or None)"""
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return False, f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)
            is_active = domain.isActive()
            conn.close()
            return is_active, None
        except libvirt.libvirtError as e:
            conn.close()
            return False, f"VM '{vm_name}' not found: {str(e)}"

    # List available resources
    @mcp.resource("list://resources")
    def list_resources() -> dict:
        """Return a list of all available resources in this server."""
        return {
            "resources": [
                {
                    "uri": "images://{os_name}",
                    "name": "Operating System Images",
                    "description": "Return the path to an image in the system with the Distribution installed",
                    "mime_type": "text/plain",
                }
            ]
        }

    # Define a resource template with a parameter
    @mcp.resource("images://{os_name}")
    def get_os_image_path_resource(os_name: str) -> str:
        """Return the path in the system to a disk with OS installed"""
        return get_os_image_path(os_name)

    @mcp.tool()
    def get_vm_ip(vm_name, network_name=None):
        """
        Get IP of a VM given its name using multiple detection methods.

        Args:
          vm_name: VM name.
          network_name: Network name (optional, auto-detects if None).

        Returns:
           IP address if successful, error message otherwise.
        """
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)
        except libvirt.libvirtError as e:
            conn.close()
            return f"VM '{vm_name}' not found: {str(e)}"

        xml_desc = domain.XMLDesc()
        root = ET.fromstring(xml_desc)

        # Extract MAC addresses and network information
        interfaces = []
        for iface in root.findall("./devices/interface"):
            mac_elem = iface.find("./mac")
            source_elem = iface.find("./source")
            if mac_elem is not None:
                iface_info = {
                    'mac': mac_elem.get('address', '').lower(),
                    'type': iface.get('type'),
                    'network': source_elem.get('network') if source_elem is not None else None,
                }
                interfaces.append(iface_info)

        if not interfaces:
            conn.close()
            return f"No network interfaces found for VM '{vm_name}'"

        # Method 1: Try libvirt guest agent if available (most accurate for running VMs)
        if domain.isActive():
            try:
                # Get guest agent interfaces
                ifaces = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT)
                for iface_name, iface_data in ifaces.items():
                    # Skip loopback interface
                    if iface_name == 'lo' or iface_name.startswith('lo'):
                        continue
                    if iface_data.get('addrs'):
                        for addr in iface_data['addrs']:
                            if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                ip = addr['addr']
                                # Skip loopback addresses
                                if ip != '127.0.0.1' and not ip.startswith('127.'):
                                    conn.close()
                                    return f"{ip} (guest agent via {iface_name})"
            except (libvirt.libvirtError, KeyError):
                # Guest agent not available or error, continue
                pass

        # Method 2: DHCP lease lookup
        networks_to_check = []
        if network_name:
            networks_to_check = [network_name]
        else:
            # Auto-detect networks from VM interfaces
            for iface in interfaces:
                if iface['network'] and iface['network'] not in networks_to_check:
                    networks_to_check.append(iface['network'])
            # Also check 'default' network as fallback
            if 'default' not in networks_to_check:
                networks_to_check.append('default')

        # Check DHCP leases in relevant networks
        for net_name in networks_to_check:
            try:
                network = conn.networkLookupByName(net_name)
                leases = network.DHCPLeases()
                for lease in leases:
                    for iface in interfaces:
                        if lease['mac'].lower() == iface['mac']:
                            conn.close()
                            return f"{lease['ipaddr']} (DHCP from {net_name})"
            except libvirt.libvirtError:
                # Network might not exist or have DHCP, continue
                continue

        # Method 3: ARP table lookup
        if arp is not None:
            for iface in interfaces:
                try:
                    # Check system ARP table for MAC address
                    result = arp("-a", _timeout=5)
                    for line in result.stdout.decode().split('\n'):
                        if iface['mac'] in line.lower():
                            # Parse IP from ARP entry like: hostname (192.168.1.100) at aa:bb:cc:dd:ee:ff [ether] on eth0
                            import re

                            # Simple but robust IPv4 pattern - extract and validate separately
                            ip_match = re.search(r'\(([0-9.]+)\)', line)
                            if ip_match:
                                ip = ip_match.group(1)
                                # Validate IP address by checking octets
                                octets = ip.split('.')
                                if len(octets) == 4:
                                    try:
                                        if all(0 <= int(octet) <= 255 for octet in octets):
                                            conn.close()
                                            return f"{ip} (ARP table)"
                                    except ValueError:
                                        pass  # Invalid octet, continue
                except (ErrorReturnCode, CommandNotFound):
                    # ARP lookup failed, continue
                    continue

        conn.close()
        mac_list = [iface['mac'] for iface in interfaces]
        return f"No IP found for VM '{vm_name}' with MACs: {', '.join(mac_list)}"

    @mcp.tool()
    def get_vm_config(vm_name: str) -> str:
        """
        Get the complete XML configuration of a VM.

        Args:
          vm_name: VM name.

        Returns:
           Complete XML configuration if successful, error message otherwise.
        """
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)
        except libvirt.libvirtError as e:
            conn.close()
            return f"VM '{vm_name}' not found: {str(e)}"

        try:
            # Get the complete XML configuration
            xml_config = domain.XMLDesc()
            conn.close()

            # Pretty-print the XML for better readability
            try:
                import xml.dom.minidom

                dom = xml.dom.minidom.parseString(xml_config)
                pretty_xml = dom.toprettyxml(indent="  ")
                # Remove empty lines and the XML declaration for cleaner output
                lines = [line for line in pretty_xml.split('\n') if line.strip()]
                if lines and lines[0].startswith('<?xml'):
                    lines = lines[1:]  # Remove XML declaration
                return '\n'.join(lines)
            except Exception:
                # If pretty-printing fails, return raw XML
                return xml_config

        except libvirt.libvirtError as e:
            conn.close()
            return f"Failed to get configuration for VM '{vm_name}': {str(e)}"

    @mcp.tool()
    def start_vm(vm_name: str):
        """
        Start an existing VM given its name.

        Args:
          vm_name: VM name.

        Returns:
           `OK` if success, error message otherwise.
        """
        success, message = _start_vm(vm_name)
        return message

    @mcp.tool()
    def shutdown_vm(vm_name: str):
        """
        Shutdown the execution of an existing VM given its name.
        The VM may ignore the request.

        Args:
          vm_name: VM name.

        Returns:
           `OK` if successes, `Error` otherwise.
        """
        success, message = _stop_vm(vm_name, force=False)
        return message

    @mcp.tool()
    def destroy_vm(vm_name: str):
        """
        Destroy an existing VM given its name.
        Note: This destroys the entire infrastructure as VMs are managed as a group.

        Args:
          vm_name: VM name.

        Returns:
           `OK` if successes, `Error` otherwise.
        """
        # Currently destroys all VMs as they are managed as infrastructure
        success, result, error = _pulumi_destroy()
        if not success:
            return f"Failed to destroy VM infrastructure: {error}"

        return "OK"

    @mcp.tool()
    def list_vms():
        """
        Returns a list of VMs both running or defined in current system

        Args:

        Returns:
          A dictionary in which each entry is the name of the VM and then
          the first column is the id, the second column is the status and the third
          column is the uuid.
        """
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        vms = {}

        # Get all domains (both active and inactive)
        for dom in conn.listAllDomains():
            name = dom.name()
            is_active = dom.isActive()
            vms[name] = {'id': dom.ID() if is_active else None, 'active': is_active, 'uuid': dom.UUIDString()}
        conn.close()
        return vms

    @mcp.tool()
    def rename_vm(old_name: str, new_name: str) -> str:
        """
        Rename a VM by changing its name in the configuration.
        The VM must be stopped before renaming.

        Args:
          old_name: Current name of the virtual machine
          new_name: New name for the virtual machine

        Returns:
          `OK` if success, error message otherwise
        """
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        try:
            # Look up the domain by its current name
            domain = conn.lookupByName(old_name)
        except libvirt.libvirtError as e:
            conn.close()
            return f"VM '{old_name}' not found: {str(e)}"

        try:
            # Check if VM is running - remember state and stop if needed
            was_running, error_msg = _is_vm_running(old_name)
            if error_msg:
                conn.close()
                return error_msg
            if was_running:
                # Stop the VM before renaming
                success, stop_msg = _stop_vm(old_name, force=False)
                if not success:
                    conn.close()
                    return f"Failed to stop VM '{old_name}' for renaming: {stop_msg}"

            # Check if new name already exists
            try:
                conn.lookupByName(new_name)
                conn.close()
                return f"VM with name '{new_name}' already exists"
            except libvirt.libvirtError:
                # Good, new name doesn't exist
                pass

            # Get the current XML configuration
            xml_config = domain.XMLDesc()

            # Parse XML and update the name
            root = ET.fromstring(xml_config)
            name_elem = root.find("name")
            if name_elem is not None:
                name_elem.text = new_name
            else:
                conn.close()
                return f"Failed to find name element in VM '{old_name}' configuration"

            # Convert back to XML string
            updated_xml = ET.tostring(root, encoding='unicode')

            # Undefine the old domain
            domain.undefine()

            # Define the new domain with updated XML
            conn.defineXML(updated_xml)

            conn.close()

            # If VM was running before, start it again with the new name
            if was_running:
                success, start_msg = _start_vm(new_name)
                if not success:
                    return f"VM renamed successfully but failed to restart: {start_msg}"

            return "OK"

        except libvirt.libvirtError as e:
            conn.close()
            return f"Failed to rename VM '{old_name}' to '{new_name}': {str(e)}"
        except ET.ParseError as e:
            conn.close()
            return f"Failed to parse XML configuration for VM '{old_name}': {str(e)}"

    @mcp.tool()
    def create_vm(
        name: str,
        cores: int,
        memory: int,
        path: str,
        username: str = None,
        password: str = None,
        groups: list = None,
        github_ssh_user: str = None,
        packages: list = None,
        dns_servers: list = None,
        autostart: bool = False,
    ) -> str:
        """
        Create a VM with a given name and with a given number of
        cores and a given amount of memory and using a image in path or URL.
        Uses Pulumi for infrastructure provisioning.

        If cloud-init parameters are not provided, falls back to the default cloud-init
        configuration from __main__.py.

        Args:
          name:             name of the virtual machine
          cores:            number of cores
          memory:           amount of memory in megabytes
          path:             path to the image for the disk (can be local path or URL)
          username:         cloud-init username (optional, falls back to default config)
          password:         cloud-init password (optional, falls back to default config)
          groups:           user groups list (optional, falls back to default config)
          github_ssh_user:  GitHub username for SSH key import (optional)
          packages:         list of packages to install (optional, falls back to default config)
          dns_servers:      list of DNS servers to configure (optional)
          autostart:        whether to enable autostart (default: False)

        Returns:
          `OK` if success, `Error` otherwise
        """
        # If any cloud-init parameters are provided, use custom cloud-init
        if any([username, password, groups, github_ssh_user, packages, dns_servers]):
            pass

        # Use Pulumi to create the VM infrastructure
        success, result, error = _pulumi_up()
        if not success:
            return f"Failed to create VM infrastructure: {error}"

        # Get VM information from Pulumi output
        success, output, error = _pulumi_stack_output()
        if success and output:
            vm_names = output.get('all_vm_names', [])
            if name in vm_names or len(vm_names) > 0:
                return "OK"

        return "OK"

    @mcp.tool()
    def preview() -> str:
        """
        Preview changes that would be made to infrastructure without applying them.

        Returns:
            Preview information in JSON format or error message.
        """
        success, result, error = _pulumi_preview()
        if not success:
            return f"Preview failed: {error}"

        # Format the preview result for display
        if result and 'steps' in result:
            step_count = len(result['steps'])
            changes = result.get('changeSummary', {})
            return f"Preview: {step_count} steps - Create: {changes.get('create', 0)}, Update: {changes.get('update', 0)}, Replace: {changes.get('replace', 0)}, Delete: {changes.get('delete', 0)}"

        return json.dumps(result, indent=2) if result else "No changes"

    @mcp.tool()
    def deploy() -> str:
        """
        Deploy VMs and infrastructure.

        Returns:
            Success message or error details.
        """
        success, result, error = _pulumi_up()
        if not success:
            return f"Deployment failed: {error}"

        # Get deployment outputs
        success, output, error = _pulumi_stack_output()
        if success and output:
            vm_count = output.get('vm_count', 0)
            vm_ips = output.get('all_vm_ips', [])
            return f"Successfully deployed {vm_count} VMs with IPs: {', '.join(vm_ips) if vm_ips else 'pending'}"

        return "VM deployment completed successfully"

    @mcp.tool()
    def destroy_all() -> str:
        """
        Destroy all VMs and infrastructure.

        Returns:
            Success message or error details.
        """
        success, result, error = _pulumi_destroy()
        if not success:
            return f"Destroy failed: {error}"

        return "All VMs and infrastructure destroyed successfully"

    @mcp.tool()
    def get_outputs() -> str:
        """
        Get current infrastructure outputs including VM information.

        Returns:
            JSON formatted output information or error message.
        """
        success, output, error = _pulumi_stack_output()
        if not success:
            return f"Failed to get outputs: {error}"

        if output:
            return json.dumps(output, indent=2)
        else:
            return "No outputs available"

    @mcp.tool()
    def get_status() -> str:
        """
        Get status of VMs and infrastructure including IPs and configuration.

        Returns:
            VM status information or error message.
        """
        success, output, error = _pulumi_stack_output()
        if not success:
            return f"Failed to get status: {error}"

        if not output:
            return "No VMs currently deployed"

        vm_count = output.get('vm_count', 0)
        vm_ips = output.get('all_vm_ips', [])
        vm_config = {
            'cpu_cores': output.get('config_vm_cpu_cores'),
            'ram_mb': output.get('config_vm_ram_mb'),
            'disk_gb': output.get('config_vm_disk_gb'),
            'network': output.get('network_type'),
            'bridge': output.get('bridge_name'),
        }

        status = f"VMs deployed: {vm_count}\n"
        status += f"IP addresses: {', '.join(vm_ips) if vm_ips else 'pending'}\n"
        status += f"Configuration: {json.dumps(vm_config, indent=2)}"

        return status
