import libvirt
import xml.etree.ElementTree as ET
from decouple import config

LIBVIRT_DEFAULT_URI = config("LIBVIRT_DEFAULT_URI", default="qemu:///system")


def register_handlers(mcp):
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

        # Method 3: ARP table lookup (requires subprocess)
        import subprocess

        for iface in interfaces:
            try:
                # Check system ARP table for MAC address
                result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
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
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
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
            # Check if VM is already running
            if domain.isActive():
                conn.close()
                return f"VM '{vm_name}' is already running"
            
            # Start the VM
            domain.create()
            conn.close()
            return "OK"
        except libvirt.libvirtError as e:
            conn.close()
            return f"Failed to start VM '{vm_name}': {str(e)}"

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
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        try:
            domain = conn.lookupByName(vm_name)

            if domain.isActive():
                domain.shutdown()

            return "OK"
        except libvirt.libvirtError as e:
            print(f"Error: {e}")

        conn.close()

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

            if domain.isActive():
                domain.destroy()

            domain.undefine()

            return "OK"
        except libvirt.libvirtError as e:
            print(f"Error: {e}")

        conn.close()

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
            vms[name] = {
                'id': dom.ID() if is_active else None,
                'active': is_active,
                'uuid': dom.UUIDString()
            }
        conn.close()
        return vms

    @mcp.tool()
    def create_vm(name: str, cores: int, memory: int, path: str) -> str:
        """
        Create a Virtual Machine (VM) with a given name and with a given number of
        cores and a given amount of memory and using a image in path.

        Args:
          name: name of the virtual machine
          cores: number of cores
          memory: amount of memory in megabytes
          path: path to the image for the disk

        Returns:
          `OK` if success, `Error` otherwise
        """
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
              <source file='{path}'/>
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
        domain.create()
        conn.close()
        return "OK"
