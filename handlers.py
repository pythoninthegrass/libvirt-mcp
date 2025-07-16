import base64
import contextlib
import hashlib
import jinja2
import libvirt
import os
import paramiko
import sh
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from decouple import config
from pathlib import Path
from urllib.parse import urlparse

LIBVIRT_DEFAULT_URI = config("LIBVIRT_DEFAULT_URI", default="qemu:///system")


class LibvirtWrapper:
    """Wrapper class for libvirt operations following the reference repository pattern."""

    def __init__(self, uri=None):
        self.uri = uri or LIBVIRT_DEFAULT_URI

    def install(self, name, osvariant, memory, cpucount, diskimg, cloudconfig_img):
        """Install a VM using virt-install command with cloud-init support.

        Args:
            name: VM name
            osvariant: OS variant (e.g., 'ubuntu22.04')
            memory: Memory in MB
            cpucount: Number of CPU cores
            diskimg: Path to disk image
            cloudconfig_img: Path to cloud-init ISO

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        try:
            # For remote SSH connections, run virt-install on the remote host
            if "ssh://" in self.uri:
                host_part = self.uri.split("://")[1].split("/")[0]
                cmd = [
                    "ssh",
                    host_part,
                    "sudo",
                    "virt-install",
                    "--name",
                    name,
                    "--virt-type",
                    "kvm",
                    "--osinfo",
                    osvariant,
                    "--memory",
                    str(memory),
                    "--vcpus",
                    str(cpucount),
                    "--network",
                    "default,model=virtio",
                    "--graphics",
                    "spice",
                    "--disk",
                    f"path={diskimg},format=qcow2,bus=virtio",
                    "--disk",
                    f"path={cloudconfig_img},device=cdrom",
                    "--import",
                    "--noautoconsole",
                ]
            else:
                # Local installation
                cmd = [
                    "virt-install",
                    "--connect",
                    self.uri,
                    "--name",
                    name,
                    "--virt-type",
                    "kvm",
                    "--osinfo",
                    osvariant,
                    "--memory",
                    str(memory),
                    "--vcpus",
                    str(cpucount),
                    "--network",
                    "default,model=virtio",
                    "--graphics",
                    "spice",
                    "--disk",
                    f"path={diskimg},format=qcow2,bus=virtio",
                    "--disk",
                    f"path={cloudconfig_img},device=cdrom",
                    "--import",
                    "--noautoconsole",
                ]

            try:
                sh.virt_install(*cmd[2:], _err_to_out=True)
            except sh.ErrorReturnCode as e:
                return False, f"virt-install failed: {e.stderr.decode()}"

            return True, None

        except Exception as e:
            return False, f"Failed to install VM: {str(e)}"

    def install_with_cloud_init(self, name, osvariant, memory, cpucount, diskimg, user_data, meta_data=None):
        """Install a VM using virt-install with modern --cloud-init support.

        This method uses virt-install's built-in --cloud-init option which handles
        ISO creation and placement automatically, including for remote connections.

        Args:
            name: VM name
            osvariant: OS variant (e.g., 'ubuntu22.04')
            memory: Memory in MB
            cpucount: Number of CPU cores
            diskimg: Path to disk image
            user_data: Cloud-init user data configuration
            meta_data: Optional cloud-init metadata (defaults to hostname)

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        try:
            # Create temporary user-data file
            with tempfile.NamedTemporaryFile(mode='w', suffix='-user-data', delete=False) as user_file:
                user_file.write(user_data)
                user_data_path = user_file.name

            # Create temporary meta-data file if provided
            meta_data_path = None
            if meta_data:
                with tempfile.NamedTemporaryFile(mode='w', suffix='-meta-data', delete=False) as meta_file:
                    meta_file.write(meta_data)
                    meta_data_path = meta_file.name

            try:
                cmd = [
                    "virt-install",
                    "--connect",
                    self.uri,
                    "--name",
                    name,
                    "--virt-type",
                    "kvm",
                    "--osinfo",
                    osvariant,
                    "--memory",
                    str(memory),
                    "--vcpus",
                    str(cpucount),
                    "--network",
                    "default,model=virtio",
                    "--graphics",
                    "spice",
                    "--disk",
                    f"path={diskimg},format=qcow2,bus=virtio",
                    "--import",
                    "--noautoconsole",
                ]

                # Add cloud-init configuration
                if meta_data_path:
                    cmd.extend(["--cloud-init", f"user-data={user_data_path},meta-data={meta_data_path}"])
                else:
                    cmd.extend(["--cloud-init", f"user-data={user_data_path}"])

                try:
                    sh.virt_install(*cmd[2:], _err_to_out=True)
                except sh.ErrorReturnCode as e:
                    return False, f"virt-install failed: {e.stderr.decode()}"

                return True, None

            finally:
                # Clean up temporary files
                with contextlib.suppress(Exception):
                    os.unlink(user_data_path)
                if meta_data_path:
                    with contextlib.suppress(Exception):
                        os.unlink(meta_data_path)

        except Exception as e:
            return False, f"Failed to install VM with cloud-init: {str(e)}"

    def check_cloud_init_support(self):
        """Check if virt-install supports the --cloud-init option.

        Returns:
            tuple: (supported: bool, version: str, message: str)
        """
        try:
            # For remote connections, run the check on the remote host
            if "ssh://" in self.uri:
                host_part = self.uri.split("://")[1].split("/")[0]

                # Get version
                try:
                    version_result = sh.ssh(host_part, "virt-install", "--version", _timeout=10)
                    version = version_result.stdout.decode().strip()
                except sh.ErrorReturnCode:
                    version = "unknown"

                # Check for --cloud-init support
                try:
                    help_result = sh.ssh(host_part, "virt-install", "--help", _timeout=10)
                    supported = "--cloud-init" in help_result.stdout.decode()
                except sh.ErrorReturnCode:
                    supported = False

                if supported:
                    return True, version, f"virt-install {version} supports --cloud-init"
                else:
                    return False, version, f"virt-install {version} does not support --cloud-init (requires 3.0+)"
            else:
                # Local check
                try:
                    version_result = sh.virt_install("--version", _timeout=10)
                    version = version_result.stdout.decode().strip()
                except sh.ErrorReturnCode:
                    version = "unknown"

                try:
                    help_result = sh.virt_install("--help", _timeout=10)
                    supported = "--cloud-init" in help_result.stdout.decode()
                except sh.ErrorReturnCode:
                    supported = False

                if supported:
                    return True, version, f"virt-install {version} supports --cloud-init"
                else:
                    return False, version, f"virt-install {version} does not support --cloud-init (requires 3.0+)"

        except Exception as e:
            return False, "unknown", f"Failed to check virt-install support: {str(e)}"

    def create_remote_cloudinit_iso(self, vm_name, user_data, meta_data):
        """Create cloud-init ISO directly on remote host (more efficient than copying).

        Args:
            vm_name: VM name for ISO filename
            user_data: Cloud-init user data content
            meta_data: Cloud-init metadata content

        Returns:
            tuple: (success: bool, iso_path: str, error_message: str or None)
        """
        if "ssh://" not in self.uri:
            return False, None, "Remote ISO creation only supported for SSH connections"

        host_part = self.uri.split("://")[1].split("/")[0]
        iso_path = f"/var/lib/libvirt/images/{vm_name}-cloudinit.iso"

        try:
            # Create temporary user-data file on remote host
            user_data_cmd = f"echo {repr(user_data)} > /tmp/{vm_name}-user-data"
            try:
                sh.ssh(host_part, "sh", "-c", user_data_cmd, _timeout=30)
            except sh.ErrorReturnCode as e:
                return False, None, f"Failed to create user-data on remote host: {e.stderr.decode()}"

            # Create temporary meta-data file on remote host
            meta_data_cmd = f"echo {repr(meta_data)} > /tmp/{vm_name}-meta-data"
            try:
                sh.ssh(host_part, "sh", "-c", meta_data_cmd, _timeout=30)
            except sh.ErrorReturnCode as e:
                return False, None, f"Failed to create meta-data on remote host: {e.stderr.decode()}"

            # Try cloud-localds first on remote host
            cloud_localds_cmd = f"cloud-localds {iso_path} /tmp/{vm_name}-user-data /tmp/{vm_name}-meta-data"
            try:
                sh.ssh(host_part, "sh", "-c", cloud_localds_cmd, _timeout=60)
                # If cloud-localds succeeds, clean up temp files and return
                with contextlib.suppress(sh.ErrorReturnCode):
                    sh.ssh(host_part, "rm", "-f", f"/tmp/{vm_name}-user-data", f"/tmp/{vm_name}-meta-data", _timeout=10)
                return True, iso_path, None
            except sh.ErrorReturnCode:
                pass

            # Fallback to mkisofs/genisoimage on remote host with sudo
            mkisofs_cmd = (
                f"sudo mkisofs -output {iso_path} -volid cidata -joliet -rock /tmp/{vm_name}-user-data /tmp/{vm_name}-meta-data"
            )
            try:
                sh.ssh(host_part, "sh", "-c", mkisofs_cmd, _timeout=60)
                # Clean up temp files
                with contextlib.suppress(sh.ErrorReturnCode):
                    sh.ssh(host_part, "rm", "-f", f"/tmp/{vm_name}-user-data", f"/tmp/{vm_name}-meta-data", _timeout=10)
                return True, iso_path, None
            except sh.ErrorReturnCode as e:
                # Clean up temp files
                with contextlib.suppress(sh.ErrorReturnCode):
                    sh.ssh(host_part, "rm", "-f", f"/tmp/{vm_name}-user-data", f"/tmp/{vm_name}-meta-data", _timeout=10)
                return False, None, f"Failed to create ISO on remote host: {e.stderr.decode()}"

        except Exception as e:
            return False, None, f"Failed to create remote ISO: {str(e)}"


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
            try:
                sh.ssh(host_part, "test", "-f", path_or_url, _timeout=10)
                return str(path_or_url), None
            except sh.ErrorReturnCode:
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
        "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img",  # Common Ubuntu image
        "/data/libvirt/images/ubuntu-24.04-base.qcow2",  # Common custom image
    ]

    # If using SSH connection, check remote paths
    if "ssh://" in LIBVIRT_DEFAULT_URI:
        host_part = LIBVIRT_DEFAULT_URI.split("://")[1].split("/")[0]

        for path in possible_paths:
            try:
                sh.ssh(host_part, "test", "-f", path, _timeout=5)
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


def register_handlers(mcp):
    # Internal helper functions for VM operations
    def _start_vm(vm_name: str):
        """Internal helper to start a VM. Returns (success: bool, message: str)"""
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
        """Internal helper to stop a VM. Returns (success: bool, message: str)"""
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
                    domain.destroy()  # Forceful shutdown
                else:
                    domain.shutdown()  # Graceful shutdown
            conn.close()
            return True, "OK"
        except libvirt.libvirtError as e:
            conn.close()
            return False, f"Failed to stop VM '{vm_name}': {str(e)}"

    def _is_vm_running(vm_name: str):
        """Internal helper to check if VM is running. Returns (is_running: bool, error_msg: str or None)"""
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
    def get_os_image_path(os_name: str) -> str:
        """Return the path in the system to a disk with OS installed"""
        # Check multiple possible locations for images
        possible_paths = [
            f"/var/lib/libvirt/images/{os_name}.qcow2",
            f"/data/libvirt/images/{os_name}.qcow2",
            f"/var/lib/libvirt/images/{os_name}.img",
            f"/data/libvirt/images/{os_name}.img",
            "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img",  # Common Ubuntu image
            "/data/libvirt/images/ubuntu-24.04-base.qcow2",  # Common custom image
        ]

        # If using SSH connection, check remote paths
        if "ssh://" in LIBVIRT_DEFAULT_URI:
            host_part = LIBVIRT_DEFAULT_URI.split("://")[1].split("/")[0]

            for path in possible_paths:
                try:
                    sh.ssh(host_part, "test", "-f", path, _timeout=5)
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

    @mcp.tool()
    def get_vm_ip(vm_name, network_name=None):
        """
        Get IP of a Virtual Machine given its name using multiple detection methods.

        Args:
          vm_name: Virtual Machine name.
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

        # Method 3: ARP table lookup (requires sh)

        for iface in interfaces:
            try:
                # Check system ARP table for MAC address
                result = sh.arp("-a", _timeout=5)
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
            except (sh.ErrorReturnCode, sh.CommandNotFound):
                # ARP lookup failed, continue
                continue

        conn.close()
        mac_list = [iface['mac'] for iface in interfaces]
        return f"No IP found for VM '{vm_name}' with MACs: {', '.join(mac_list)}"

    @mcp.tool()
    def get_vm_config(vm_name: str) -> str:
        """
        Get the complete XML configuration of a Virtual Machine.

        Args:
          vm_name: Virtual Machine name.

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
        Start an existing Virtual Machine (VM) given its name.

        Args:
          vm_name: Virtual Machine name.

        Returns:
           `OK` if success, error message otherwise.
        """
        success, message = _start_vm(vm_name)
        return message

    @mcp.tool()
    def shutdown_vm(vm_name: str):
        """
        Shutdown the execution of an existing Virtual Machine(VM) given its name.
        The VM may ignore the request.

        Args:
          vm_name: Virtual Machine name.

        Returns:
           `OK` if successes, `Error` otherwise.
        """
        success, message = _stop_vm(vm_name, force=False)
        return message

    @mcp.tool()
    def destroy_vm(vm_name: str):
        """
        Destroy an existing Virtual Machine(VM) given its name. This method
        destroys and undefines the VM.

        Args:
          vm_name: Virtual Machine name.

        Returns:
           `OK` if successes, `Error` otherwise.
        """
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)

            # Use helper function to forcefully stop the VM
            success, message = _stop_vm(vm_name, force=True)
            if not success:
                conn.close()
                return message

            domain.undefine()
            conn.close()
            return "OK"
        except libvirt.libvirtError as e:
            conn.close()
            return f"Failed to destroy VM '{vm_name}': {str(e)}"

    @mcp.tool()
    def list_vms():
        """
        Returns a list of Virtual Machines (VMs) both running or defined in current system

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
        Rename a Virtual Machine by changing its name in the configuration.
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

    def get_ssh_public_key():
        """Read SSH public key from libvirt host as fallback to GitHub import."""
        try:
            # Extract host from LIBVIRT_DEFAULT_URI
            if "qemu+ssh://" in LIBVIRT_DEFAULT_URI:
                host = LIBVIRT_DEFAULT_URI.split("qemu+ssh://")[1].split("/")[0]
                username = host.split("@")[0] if "@" in host else "ubuntu"
                hostname = host.split("@")[1] if "@" in host else host

                # Connect via SSH to read the public key
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname, username=username)

                stdin, stdout, stderr = ssh.exec_command("cat ~/.ssh/id_rsa.pub")
                ssh_key = stdout.read().decode().strip()
                ssh.close()

                return ssh_key if ssh_key else None
            else:
                # Fallback to local key if not using SSH connection
                ssh_key_path = Path.home() / ".ssh" / "id_rsa.pub"
                if ssh_key_path.exists():
                    return ssh_key_path.read_text().strip()
                return None
        except Exception:
            return None

    def _build_ssh_keys_context(ssh_public_key=None, github_ssh_user=None):
        """Build semantic SSH keys context for Jinja2 template rendering."""
        ssh_keys_parts = []

        # Add GitHub SSH key import
        if github_ssh_user:
            ssh_keys_parts.extend(["ssh_import_id:", f"      - gh:{github_ssh_user}"])

        # Add fallback SSH public key if available
        if ssh_public_key:
            ssh_keys_parts.extend(["    ssh_authorized_keys:", f"      - {ssh_public_key}"])

        return "\n".join(ssh_keys_parts)

    def create_cloud_init_user_data(
        username="admin", password="ubuntu", groups=None, github_ssh_user=None, packages=None, dns_servers=None
    ):
        """Create cloud-init user data using Jinja2 template."""
        if groups is None:
            groups = ["sudo"]
        if packages is None:
            packages = ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"]

        # Get SSH public key as fallback
        ssh_public_key = get_ssh_public_key()

        # Build ssh_keys section with semantic variables
        ssh_keys_context = _build_ssh_keys_context(ssh_public_key, github_ssh_user)

        # Load and render template
        template_path = Path(__file__).parent / "cloud-init.yml.j2"
        template_loader = jinja2.FileSystemLoader(template_path.parent)
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template("cloud-init.yml.j2")

        user_data = template.render(
            username=username,
            password=password,
            groups=groups,
            ssh_keys_section=ssh_keys_context,
            github_ssh_user=github_ssh_user,
            packages=packages,
            dns_servers=dns_servers,
        )
        return user_data

    def generate_cloudinit_iso(meta_data, user_data, iso_filename):
        """Generate a cloud-init ISO file from metadata and user data.

        Args:
            meta_data: Cloud-init metadata configuration
            user_data: Cloud-init user data configuration
            iso_filename: Path where the generated ISO will be saved

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        try:
            # Create temporary files for metadata and user data
            with tempfile.NamedTemporaryFile(mode='w', suffix='-meta-data', delete=False) as meta_file:
                meta_file.write(meta_data)
                meta_file_path = meta_file.name

            with tempfile.NamedTemporaryFile(mode='w', suffix='-user-data', delete=False) as user_file:
                user_file.write(user_data)
                user_file_path = user_file.name

            try:
                # Try cloud-localds first (recommended method)
                try:
                    sh.cloud_localds(iso_filename, user_file_path, meta_file_path)
                    return True, None
                except sh.CommandNotFound:
                    # Fallback to genisoimage/mkisofs
                    return _create_iso_with_genisoimage(iso_filename, meta_file_path, user_file_path)
                except sh.ErrorReturnCode as e:
                    return False, f"cloud-localds failed: {e.stderr.decode()}"

            finally:
                # Clean up temporary files
                with contextlib.suppress(Exception):
                    os.unlink(meta_file_path)
                with contextlib.suppress(Exception):
                    os.unlink(user_file_path)

        except Exception as e:
            return False, f"Failed to generate cloud-init ISO: {str(e)}"

    def _create_iso_with_genisoimage(iso_filename, meta_file_path, user_file_path):
        """Fallback method to create ISO using genisoimage/mkisofs."""
        try:
            # Find available ISO creation tool and create the ISO
            try:
                sh.genisoimage("-output", iso_filename, "-volid", "cidata", "-joliet", "-rock", user_file_path, meta_file_path)
                return True, None
            except sh.CommandNotFound:
                try:
                    sh.mkisofs("-output", iso_filename, "-volid", "cidata", "-joliet", "-rock", user_file_path, meta_file_path)
                    return True, None
                except sh.CommandNotFound:
                    return (
                        False,
                        "Neither cloud-localds nor genisoimage/mkisofs found. Please install cloud-image-utils or genisoimage package.",
                    )
                except sh.ErrorReturnCode as e:
                    # Check if it's just configuration file permission warnings
                    if "Permission denied. Cannot open '.mkisofsrc'" in e.stderr.decode() and Path(iso_filename).exists():
                        # These are warnings about config files, not fatal errors
                        # Check if ISO was actually created
                        return True, None
                    return False, f"Failed to create ISO: {e.stderr.decode()}"
            except sh.ErrorReturnCode as e:
                # Check if it's just configuration file permission warnings
                if "Permission denied. Cannot open '.genisoimagerc'." in e.stderr.decode() and Path(iso_filename).exists():
                    # These are warnings about config files, not fatal errors
                    # Check if ISO was actually created
                    return True, None
                return False, f"Failed to create ISO: {e.stderr.decode()}"

        except Exception as e:
            return False, f"Failed to create ISO with genisoimage: {str(e)}"

    @mcp.tool()
    def create_vm(name: str, cores: int, memory: int, path: str, autostart: bool = False) -> str:
        """
        Create a Virtual Machine (VM) with a given name and with a given number of
        cores and a given amount of memory and using a image in path or URL.

        Args:
          name: name of the virtual machine
          cores: number of cores
          memory: amount of memory in megabytes
          path: path to the image for the disk (can be local path or URL)
          autostart: whether to enable autostart (default: False)

        Returns:
          `OK` if success, `Error` otherwise
        """
        # Resolve the image path (handles URLs and local paths)
        resolved_path, path_error = _resolve_image_path(path)
        if path_error:
            return f"Image resolution failed: {path_error}"

        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        # XML definition of the VM
        # set parameters from arguments
        domain_xml = f"""
        <domain type='kvm'>
          <name>{name}</name>
          <memory unit='MiB'>{memory}</memory>
          <vcpu>{cores}</vcpu>
          <os>
            <type arch='x86_64'>hvm</type>
            <boot dev='hd'/>
          </os>
          <devices>
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{resolved_path}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            <console type='pty' tty='/dev/pts/2'>
            </console>
            <interface type='network'>
            <source network='default'/>
            <model type='virtio'/>
            </interface>
          </devices>
        </domain>
        """
        try:
            domain = conn.defineXML(domain_xml)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        # TODO: to check if this fails, e.g., VM already exists
        # Set autostart for the domain based on parameter
        domain.setAutostart(autostart)

        conn.close()

        # Use helper function to start the VM
        success, message = _start_vm(name)
        return message

    @mcp.tool()
    def create_vm_with_cloudinit_install(
        name: str,
        cores: int,
        memory: int,
        path: str,
        osvariant: str = "ubuntu24.04",
        username: str = "ubuntu",
        password: str = "ubuntu",
        groups: list = None,
        github_ssh_user: str = None,
        packages: list = None,
        dns_servers: list = None,
        autostart: bool = False,
    ) -> str:
        """
        Create a VM using the LibvirtWrapper.install method pattern from the reference repository.

        Args:
            name: name of the virtual machine
            cores: number of cores
            memory: amount of memory in megabytes
            path: path to the image for the disk (can be local path or URL)
            osvariant: OS variant for virt-install (default: ubuntu22.04)
            username: cloud-init username (default: admin)
            password: cloud-init password (default: ubuntu)
            groups: user groups list (default: ["sudo"])
            github_ssh_user: GitHub username for SSH key import (optional)
            packages: list of packages to install (default: ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"])
            dns_servers: list of DNS servers to configure (optional)
            autostart: whether to enable autostart (default: False)

        Returns:
            `OK` if success, `Error` otherwise
        """
        if groups is None:
            groups = ["sudo"]
        if packages is None:
            packages = ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"]

        # Resolve the image path (handles URLs and local paths)
        resolved_path, path_error = _resolve_image_path(path)
        if path_error:
            return f"Image resolution failed: {path_error}"

        # Create cloud-init user data
        user_data = create_cloud_init_user_data(
            username=username,
            password=password,
            groups=groups,
            github_ssh_user=github_ssh_user,
            packages=packages,
            dns_servers=dns_servers,
        )

        # Create cloud-init ISO using the new function
        iso_path = f"/var/lib/libvirt/images/{name}-cloudinit.iso"
        meta_data = f"instance-id: {name}\nlocal-hostname: {name}\n"

        success, iso_error = generate_cloudinit_iso(meta_data, user_data, iso_path)
        if not success:
            return f"Cloud-init ISO creation failed: {iso_error}"

        # Use LibvirtWrapper to install the VM
        lvw = LibvirtWrapper()
        success, install_error = lvw.install(
            name=name,
            osvariant=osvariant,
            memory=memory,
            cpucount=cores,
            diskimg=resolved_path,
            cloudconfig_img=iso_path,
        )

        if not success:
            # Clean up ISO file if VM creation fails
            with contextlib.suppress(Exception):
                os.remove(iso_path)
            return f"VM installation failed: {install_error}"

        # Set autostart if requested
        if autostart:
            try:
                conn = libvirt.open(LIBVIRT_DEFAULT_URI)
                domain = conn.lookupByName(name)
                domain.setAutostart(autostart)
                conn.close()
            except Exception as e:
                # Don't fail the entire operation if autostart fails
                pass

        return "OK"

    @mcp.tool()
    def create_vm_with_cloudinit(
        name: str,
        cores: int,
        memory: int,
        path: str,
        username: str = "admin",
        password: str = "ubuntu",
        groups: list = None,
        github_ssh_user: str = None,
        packages: list = None,
        dns_servers: list = None,
        autostart: bool = False,
    ) -> str:
        """
        Create a Virtual Machine (VM) with cloud-init support for automated user setup.

        Args:
          name: name of the virtual machine
          cores: number of cores
          memory: amount of memory in megabytes
          path: path to the image for the disk (can be local path or URL)
          username: cloud-init username (default: admin)
          password: cloud-init password (default: ubuntu)
          groups: user groups list (default: ["sudo"])
          github_ssh_user: GitHub username for SSH key import (optional)
          packages: list of packages to install (default: ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"])
          dns_servers: list of DNS servers to configure (optional)
          autostart: whether to enable autostart (default: False)

        Returns:
          `OK` if success, `Error` otherwise
        """
        if groups is None:
            groups = ["sudo"]
        if packages is None:
            packages = ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"]

        # Resolve the image path (handles URLs and local paths)
        resolved_path, path_error = _resolve_image_path(path)
        if path_error:
            return f"Image resolution failed: {path_error}"

        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        # Create cloud-init user data
        user_data = create_cloud_init_user_data(
            username=username,
            password=password,
            groups=groups,
            github_ssh_user=github_ssh_user,
            packages=packages,
            dns_servers=dns_servers,
        )

        # Create cloud-init ISO using the new function
        iso_path = f"/var/lib/libvirt/images/{name}-cloudinit.iso"
        meta_data = f"instance-id: {name}\nlocal-hostname: {name}\n"

        success, iso_error = generate_cloudinit_iso(meta_data, user_data, iso_path)
        if not success:
            conn.close()
            return f"Cloud-init ISO creation failed: {iso_error}"

        # Generate a random MAC address for the VM
        import random

        mac = "52:54:00:" + ":".join([f"{random.randint(0, 255):02x}" for _ in range(3)])

        # XML definition of the VM with cloud-init support
        domain_xml = f"""
        <domain type='kvm'>
          <name>{name}</name>
          <memory unit='MiB'>{memory}</memory>
          <vcpu>{cores}</vcpu>
          <os>
            <type arch='x86_64'>hvm</type>
            <boot dev='hd'/>
          </os>
          <devices>
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{resolved_path}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            <disk type='file' device='cdrom'>
              <driver name='qemu' type='raw'/>
              <source file='{iso_path}'/>
              <target dev='hda' bus='ide'/>
              <readonly/>
            </disk>
            <console type='pty' tty='/dev/pts/2'>
            </console>
            <interface type='network'>
              <mac address='{mac}'/>
              <source network='default'/>
              <model type='virtio'/>
            </interface>
          </devices>
        </domain>
        """
        try:
            domain = conn.defineXML(domain_xml)
        except libvirt.libvirtError as e:
            # Clean up ISO file if VM creation fails
            with contextlib.suppress(Exception):
                os.remove(iso_path)
            conn.close()
            return f"Libvirt error: {str(e)}"

        # Set autostart for the domain based on parameter
        domain.setAutostart(autostart)

        conn.close()

        # Use helper function to start the VM
        success, message = _start_vm(name)
        return message

    @mcp.tool()
    def create_vm_with_modern_cloudinit(
        name: str,
        cores: int,
        memory: int,
        path: str,
        osvariant: str = "ubuntu24.04",
        username: str = "ubuntu",
        password: str = "ubuntu",
        groups: list = None,
        github_ssh_user: str = None,
        packages: list = None,
        dns_servers: list = None,
        autostart: bool = False,
    ) -> str:
        """
        Create a VM using modern virt-install --cloud-init support (recommended).

        This method uses virt-install's built-in --cloud-init option which automatically
        handles ISO creation and placement, including for remote libvirt connections.
        No manual ISO copying required.

        Args:
            name: name of the virtual machine
            cores: number of cores
            memory: amount of memory in megabytes
            path: path to the image for the disk (can be local path or URL)
            osvariant: OS variant for virt-install (default: ubuntu24.04)
            username: cloud-init username (default: ubuntu)
            password: cloud-init password (default: ubuntu)
            groups: user groups list (default: ["sudo"])
            github_ssh_user: GitHub username for SSH key import (optional)
            packages: list of packages to install (default: ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"])
            dns_servers: list of DNS servers to configure (optional)
            autostart: whether to enable autostart (default: False)

        Returns:
            `OK` if success, `Error` otherwise
        """
        if groups is None:
            groups = ["sudo"]
        if packages is None:
            packages = ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"]

        # Resolve the image path (handles URLs and local paths)
        resolved_path, path_error = _resolve_image_path(path)
        if path_error:
            return f"Image resolution failed: {path_error}"

        # Check if modern cloud-init support is available
        lvw = LibvirtWrapper()
        supported, version, message = lvw.check_cloud_init_support()
        if not supported:
            return f"Error: {message}. Please use create_vm_with_cloudinit_install instead."

        # Create cloud-init user data
        user_data = create_cloud_init_user_data(
            username=username,
            password=password,
            groups=groups,
            github_ssh_user=github_ssh_user,
            packages=packages,
            dns_servers=dns_servers,
        )

        # Create metadata
        meta_data = f"instance-id: {name}\nlocal-hostname: {name}\n"

        # Use LibvirtWrapper with modern cloud-init support
        success, install_error = lvw.install_with_cloud_init(
            name=name,
            osvariant=osvariant,
            memory=memory,
            cpucount=cores,
            diskimg=resolved_path,
            user_data=user_data,
            meta_data=meta_data,
        )

        if not success:
            return f"VM installation failed: {install_error}"

        # Set autostart if requested
        if autostart:
            try:
                conn = libvirt.open(LIBVIRT_DEFAULT_URI)
                domain = conn.lookupByName(name)
                domain.setAutostart(autostart)
                conn.close()
            except Exception as e:
                # Don't fail the entire operation if autostart fails
                pass

        return "OK"

    @mcp.tool()
    def create_vm_with_remote_cloudinit(
        name: str,
        cores: int,
        memory: int,
        path: str,
        osvariant: str = "ubuntu24.04",
        username: str = "ubuntu",
        password: str = "ubuntu",
        groups: list = None,
        github_ssh_user: str = None,
        packages: list = None,
        dns_servers: list = None,
        autostart: bool = False,
    ) -> str:
        """
        Create a VM with cloud-init using remote ISO creation (efficient for SSH connections).

        This method creates the cloud-init ISO directly on the remote host instead of
        copying it, which is more efficient for SSH connections to remote libvirt hosts.

        Args:
            name: name of the virtual machine
            cores: number of cores
            memory: amount of memory in megabytes
            path: path to the image for the disk (can be local path or URL)
            osvariant: OS variant for virt-install (default: ubuntu24.04)
            username: cloud-init username (default: ubuntu)
            password: cloud-init password (default: ubuntu)
            groups: user groups list (default: ["sudo"])
            github_ssh_user: GitHub username for SSH key import (optional)
            packages: list of packages to install (default: ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"])
            dns_servers: list of DNS servers to configure (optional)
            autostart: whether to enable autostart (default: False)

        Returns:
            `OK` if success, `Error` otherwise
        """
        if groups is None:
            groups = ["sudo"]
        if packages is None:
            packages = ["curl", "git", "openssh-server", "qemu-guest-agent", "wget"]

        # Resolve the image path (handles URLs and local paths)
        resolved_path, path_error = _resolve_image_path(path)
        if path_error:
            return f"Image resolution failed: {path_error}"

        # Create cloud-init user data
        user_data = create_cloud_init_user_data(
            username=username,
            password=password,
            groups=groups,
            github_ssh_user=github_ssh_user,
            packages=packages,
            dns_servers=dns_servers,
        )

        # Create metadata
        meta_data = f"instance-id: {name}\nlocal-hostname: {name}\n"

        # Create cloud-init ISO on remote host
        lvw = LibvirtWrapper()
        success, iso_path, iso_error = lvw.create_remote_cloudinit_iso(name, user_data, meta_data)
        if not success:
            return f"Cloud-init ISO creation failed: {iso_error}"

        # Use LibvirtWrapper to install the VM with the remote ISO
        success, install_error = lvw.install(
            name=name,
            osvariant=osvariant,
            memory=memory,
            cpucount=cores,
            diskimg=resolved_path,
            cloudconfig_img=iso_path,
        )

        if not success:
            # Clean up ISO file if VM creation fails
            if "ssh://" in LIBVIRT_DEFAULT_URI:
                host_part = LIBVIRT_DEFAULT_URI.split("://")[1].split("/")[0]
                with contextlib.suppress(sh.ErrorReturnCode):
                    sh.ssh(host_part, "sudo", "rm", "-f", iso_path, _timeout=10)
            return f"VM installation failed: {install_error}"

        # Set autostart if requested
        if autostart:
            try:
                conn = libvirt.open(LIBVIRT_DEFAULT_URI)
                domain = conn.lookupByName(name)
                domain.setAutostart(autostart)
                conn.close()
            except Exception as e:
                # Don't fail the entire operation if autostart fails
                pass

        return "OK"
