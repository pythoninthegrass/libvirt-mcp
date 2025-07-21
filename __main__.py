import pulumi
import pulumi_libvirt as libvirt
from config import (
    base_image_name,
    base_image_path,
    base_ip,
    gateway_ip,
    generate_cloud_init_with_static_ip,
    get_static_ip,
    image_format,
    libvirt_uri,
    network_cidr,
    num_vms,
    provider,
    storage_pool,
    vm_bridge,
    vm_cpu,
    vm_disk,
    vm_name_prefix,
    vm_ram,
)


def create_cloud_init_disk(vm_index, vm_name):
    """Creates a cloud-init disk for the given VM index with static IP configuration."""
    # Use simple cloud-init configuration
    default_cloud_init = """
    #cloud-config
    users:
    - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        shell: /bin/bash
    ssh_pwauth: true
    chpasswd:
    list: |
        ubuntu:ubuntu
    expire: false
    """

    return libvirt.CloudinitDisk(
        f"cloud-init-disk-{vm_index}",
        user_data=default_cloud_init,
        pool=storage_pool,
        opts=pulumi.ResourceOptions(provider=provider),
    )


def get_base_volume():
    """References the existing base volume created via virsh."""
    return base_image_name


def create_volume(vm_index, base_volume_name):
    """Creates a volume for the given VM index based on the base volume."""
    volume_args = {
        "name": f"{vm_name_prefix}-{vm_index}-volume",
        "pool": storage_pool,
        "base_volume_name": base_volume_name,
        "format": image_format,
        "opts": pulumi.ResourceOptions(provider=provider),
    }

    # Only specify size if vm_disk is larger than base volume
    # If vm_disk is specified and > 0, resize the volume
    if vm_disk and vm_disk > 0:
        volume_args["size"] = vm_disk * 1024 * 1024 * 1024  # Convert GB to bytes

    return libvirt.Volume(
        f"{vm_name_prefix}-{vm_index}-volume",
        **volume_args
    )


def create_vm(vm_index, cloud_init_disk, volume):
    """Creates a virtual machine with specified parameters using bridge networking."""
    vm_name = f"{vm_name_prefix}-{vm_index + 1}"
    return libvirt.Domain(
        vm_name,
        name=vm_name,
        memory=vm_ram,
        vcpu=vm_cpu,
        type="kvm",
        arch="x86_64",
        cloudinit=cloud_init_disk.id,
        disks=[{"volume_id": volume.id, "scsi": True}],
        network_interfaces=[
            {
                "bridge": vm_bridge,
                "model": "virtio",
                "wait_for_lease": False,
            }
        ],
        consoles=[{"type": "pty", "target_type": "serial", "target_port": "0"}],
        opts=pulumi.ResourceOptions(provider=provider),
    )


# Debug: Print configuration
print("=== Pulumi Configuration ===")
print(f"Libvirt URI: {libvirt_uri}")
print(f"Number of VMs: {num_vms}")
print(f"VM name prefix: {vm_name_prefix}")
print(f"Storage pool: {storage_pool}")
print(f"Image format: {image_format}")
print(f"Base image: {base_image_name}")
print(f"Base image path: {base_image_path}")
print(f"VM CPU cores: {vm_cpu}")
print(f"VM RAM (MB): {vm_ram}")
print(f"VM disk size (GB): {vm_disk}")
print(f"VM bridge: {vm_bridge}")
print("=== Network Configuration ===")
print(f"Base IP range: {get_static_ip(0)} - {get_static_ip(num_vms-1) if num_vms > 1 else get_static_ip(0)}")
print(f"Base IP prefix: {base_ip}")
print(f"Gateway IP: {gateway_ip}")
print(f"Network CIDR: {network_cidr}")
print("===============================")

# Provision the VMs with static IPs
base_volume_name = get_base_volume()
static_ips = []
vms = []

for i in range(num_vms):
    vm_index = i
    vm_name = f"{vm_name_prefix}-{i + 1}"
    static_ip = get_static_ip(vm_index)
    static_ips.append(static_ip)

    # Create cloud-init disk with static IP configuration
    cloud_init_disk = create_cloud_init_disk(vm_index, vm_name)

    # Create VM volume
    volume = create_volume(i, base_volume_name)

    # Create VM with bridge networking
    vm = create_vm(vm_index, cloud_init_disk, volume)
    vms.append(vm)

    # Export individual VM information
    pulumi.export(f"{vm_name}_ip", static_ip)
    pulumi.export(f"{vm_name}_name", vm.name)

# Export aggregate information
pulumi.export("all_vm_ips", static_ips)
pulumi.export("vm_count", num_vms)
pulumi.export("network_type", "bridge")
pulumi.export("bridge_name", vm_bridge)

# Export configuration values for visibility
pulumi.export("config_vm_cpu_cores", vm_cpu)
pulumi.export("config_vm_ram_mb", vm_ram)
pulumi.export("config_vm_disk_gb", vm_disk)
pulumi.export("config_base_ip_prefix", base_ip)
pulumi.export("config_gateway_ip", gateway_ip)
pulumi.export("config_network_cidr", network_cidr)
pulumi.export("config_base_image", base_image_name)
pulumi.export("config_storage_pool", storage_pool)
