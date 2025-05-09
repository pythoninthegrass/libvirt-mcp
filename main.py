from mcp.server.fastmcp import FastMCP
import xml.etree.ElementTree as ET
import libvirt

# Create an MCP server
mcp = FastMCP("libvirt-mcp-demo")

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
        conn = libvirt.open("qemu:///system")
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
def destroy_vm(vm_name: str):
    """
    Destroy an existing Virtual Machine(VM) given its name. This methos both
    destroys and undefines the VM.

    Args:
      vm_name: Virtual Machine name.

    Returns:
       `OK` if successes, `Error` otherwise.
    """
    try:
        conn = libvirt.open("qemu:///system")
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
        conn = libvirt.open("qemu:///system")
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
        conn = libvirt.open("qemu:///system")
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
        <mac address='52:54:00:0c:94:61'/>
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

def main():
    print("Hello from libvirt-mcp-demo!")

if __name__ == "__main__":
    mcp.run(transport="stdio")
