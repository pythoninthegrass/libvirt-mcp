# server.py
from mcp.server.fastmcp import FastMCP
import libvirt

# Create an MCP server
mcp = FastMCP("libvirt-mcp-demo")

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
        <graphics type='vnc' port='-1'/>
      </devices>
    </domain>
    """
    try:
        domain = conn.defineXML(domain_xml)
    except libvirt.libvirtError as e:
        return f"Libvirt error: {str(e)}"

    domain.create()
    conn.close()
    return "OK"

def main():
    print("Hello from mcp-server-demo!")

if __name__ == "__main__":
    mcp.run(transport="stdio")
