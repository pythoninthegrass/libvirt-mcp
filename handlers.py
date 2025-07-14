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
    def get_vm_ip(vm_name, network_name='default'):
        """
        Get IP of a Virtual Machine given its name.

        Args:
          vm_name: Virtual Machine name.

        Returns:
           IP if successes, `Error` otherwise.
        """
        try:
            conn = libvirt.open(LIBVIRT_DEFAULT_URI)
        except libvirt.libvirtError as e:
            return f"Libvirt error: {str(e)}"

        domain = conn.lookupByName(vm_name)

        xml_desc = domain.XMLDesc()
        root = ET.fromstring(xml_desc)

        macs = []
        for iface in root.findall("./devices/interface/mac"):
            mac = iface.get('address')
            if mac:
                macs.append(mac.lower())

        if not macs:
            return None

        network = conn.networkLookupByName(network_name)
        leases = network.DHCPLeases()

        for lease in leases:
            if lease['mac'].lower() in macs:
                return lease['ipaddr']

        return None

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
