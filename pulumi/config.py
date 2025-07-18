import pulumi
import pulumi_libvirt as libvirt
from dataclasses import dataclass
from decouple import config
from pathlib import Path
from typing import Optional

# env vars
libvirt_uri = config('LIBVIRT_DEFAULT_URI', default=pulumi.Config().get('libvirt_uri', 'qemu:///system'))
num_vms = config('NUM_VMS', default=pulumi.Config().get_int('num_vms', 1))
vm_user = config('VM_USER', default=pulumi.Config().get('vm_user', 'ubuntu'))
vm_pass = config('VM_PASS', default=pulumi.Config().get('vm_pass', 'ubuntu'))
vm_pass = vm_pass if vm_pass else vm_user
vm_cpu = config('VM_CPU', default=pulumi.Config().get_int('vm_cpu', 4))
vm_ram = config('VM_RAM', default=pulumi.Config().get_int('vm_ram', 8192))
vm_disk = config('VM_DISK', default=pulumi.Config().get_int('vm_disk', 32))
vm_bridge = config('VM_BRIDGE', default=pulumi.Config().get('vm_bridge', 'br0'))
domain = config('DOMAIN', default=pulumi.Config().get('domain', 'pulumi.local'))
dns_servers = [
    config('DNS1', default=pulumi.Config().get('dns1', '8.8.8.8')),
    config('DNS2', default=pulumi.Config().get('dns2', '8.8.4.4'))
]
addr_start = config('ADDR_START', default=pulumi.Config().get('addr_start', '192.168.122.2'))
addr_end = config('ADDR_END', default=pulumi.Config().get('addr_end', '192.168.122.254'))
network_type = config('NETWORK_TYPE', default=pulumi.Config().get('network_type', 'bridge'))

# VM and image configuration
base_image_name = config('BASE_IMAGE_NAME', default=pulumi.Config().get('base_image_name', 'ubuntu-base-volume'))
base_image_path = config('BASE_IMAGE_PATH', default=pulumi.Config().get('base_image_path', '/data/libvirt/images/ubuntu-24.04-base.qcow2'))
vm_name_prefix = config('VM_NAME_PREFIX', default=pulumi.Config().get('vm_name_prefix', 'ubuntu'))
storage_pool = config('STORAGE_POOL', default=pulumi.Config().get('storage_pool', 'default'))
image_format = config('IMAGE_FORMAT', default=pulumi.Config().get('image_format', 'qcow2'))

# pulumi provider
provider = libvirt.Provider("libvirt", uri=libvirt_uri)

# user data for cloud-init
cloud_init_data = f"""
#cloud-config
output: {{all: '| tee -a /var/log/cloud-init.log'}}
package_update: true
package_upgrade: false
packages:
  - curl
  - git
  - openssh-server
  - qemu-guest-agent
  - wget
users:
  - name: {vm_user}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo
    plain_text_passwd: '{vm_pass}'
    lock_passwd: false
    shell: /bin/bash
ssh_pwauth: true
disable_root: false
"""


@dataclass
class NetworkConfig:
    name: str
    mode: str
    domain_name: str
    dns_forwarders: list[str]
    bridge: str | None = None
    address_start: str | None = None
    address_end: str | None = None

    def get_cidr(self) -> str | None:
        """Extract CIDR notation from address_start."""
        if not self.address_start:
            return None

        # Extract base IP from address_start (e.g., "192.168.122.2" -> "192.168.122.0/24")
        parts = self.address_start.split('.')
        if len(parts) == 4:
            base_ip = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
            return base_ip
        return None


# Network configurations
network_configs = {
    'bridge': NetworkConfig(
        name="bridge_network",
        mode="bridge",
        domain_name=domain,
        dns_forwarders=dns_servers,
        bridge=vm_bridge
    ),
    'nat': NetworkConfig(
        name="nat_network",
        mode="nat",
        domain_name=domain,
        dns_forwarders=dns_servers,
        address_start=addr_start,
        address_end=addr_end
    ),
    'isolated': NetworkConfig(
        name="isolated_network",
        mode="isolated",
        domain_name=domain,
        dns_forwarders=[]
    )
}
