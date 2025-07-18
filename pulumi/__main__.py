import pulumi
import pulumi_libvirt as libvirt
from config import (
    NetworkConfig,
    base_image_name,
    base_image_path,
    cloud_init_data,
    image_format,
    libvirt_uri,
    network_configs,
    network_type,
    num_vms,
    provider,
    storage_pool,
    vm_cpu,
    vm_disk,
    vm_name_prefix,
    vm_ram,
)


def create_cloud_init_disk(vm_index):
    """
    Creates a cloud-init disk for the given VM index.

    Args:
        vm_index (int): The index of the VM for which the cloud-init disk is being created.

    Returns:
        libvirt.CloudinitDisk: The created cloud-init disk resource.
    """
    return libvirt.CloudinitDisk(
        f"cloud-init-disk-{vm_index}",
        user_data=cloud_init_data,
        pool=storage_pool,
        opts=pulumi.ResourceOptions(provider=provider)
    )


def get_base_volume():
    """
    References the existing base volume created via virsh.
    
    To create the base volume manually, run:
    ssh <host> "sudo virsh vol-create-as {storage_pool} {base_image_name} 0 --format {image_format} --backing-vol {base_image_path} --backing-vol-format {image_format}"

    Returns:
        str: The name of the existing base volume.
    """
    return base_image_name


def create_volume(vm_index, base_volume_name):
    """
    Creates a volume for the given VM index based on the base volume.

    Args:
        vm_index (int): The index of the VM for which the volume is being created.
        base_volume_name (str): The name of the base volume to clone from.

    Returns:
        libvirt.Volume: The created volume resource.
    """
    return libvirt.Volume(
        f"{vm_name_prefix}-{vm_index}-volume",
        name=f"{vm_name_prefix}-{vm_index}-volume",
        pool=storage_pool,
        base_volume_name=base_volume_name,
        size=vm_disk * 1024 * 1024 * 1024,  # Convert GB to bytes
        format=image_format,
        opts=pulumi.ResourceOptions(provider=provider)
    )


def create_network(config: NetworkConfig) -> libvirt.Network:
    """Create a libvirt network from configuration."""
    args = {
        "name": config.name,
        "mode": config.mode,
        "opts": pulumi.ResourceOptions(provider=provider)
    }

    match config.mode:
        case "bridge":
            if config.bridge:
                args["bridge"] = config.bridge
        case "nat":
            args["domain"] = config.domain_name
            cidr = config.get_cidr()
            if cidr:
                args["addresses"] = [cidr]
                args["dhcp"] = {"enabled": True}
            if config.dns_forwarders:
                args["dns"] = {
                    "enabled": True,
                    "forwarders": [
                        {"address": addr}
                        for addr in config.dns_forwarders
                    ]
                }
        case "isolated":
            args["domain"] = config.domain_name
            if config.dns_forwarders:
                args["dns"] = {
                    "enabled": True,
                    "forwarders": [
                        {"address": addr}
                        for addr in config.dns_forwarders
                    ]
                }

    return libvirt.Network(config.name, **args)


def create_vm(vm_index, cloud_init_disk, volume, network):
    """
    Creates a virtual machine with specified parameters.

    Args:
        vm_index (int): The index of the VM being created.
        cloud_init_disk (libvirt.CloudinitDisk): The cloud-init disk resource for the VM.
        volume (libvirt.Volume): The volume resource for the VM.
        network (libvirt.Network): The network to attach the VM to.

    Returns:
        libvirt.Domain: The created virtual machine resource.
    """
    return libvirt.Domain(
        f"{vm_name_prefix}-{vm_index + 1}",
        name=f"{vm_name_prefix}-{vm_index + 1}",
        memory=vm_ram,
        vcpu=vm_cpu,
        type="kvm",
        arch="x86_64",
        cloudinit=cloud_init_disk.id,
        disks=[{"volume_id": volume.id, "scsi": True}],
        network_interfaces=[{"network_name": network.name, "type": "network", "model": "virtio"}],
        consoles=[{"type": "pty", "target_type": "serial", "target_port": "0"}],
        opts=pulumi.ResourceOptions(provider=provider)
    )


# Debug: Print configuration
print(f"Using libvirt URI: {libvirt_uri}")
print(f"Base image: {base_image_name} (from {base_image_path})")
print(f"VM name prefix: {vm_name_prefix}")
print(f"Storage pool: {storage_pool}")
print(f"Image format: {image_format}")

# Create only the selected network
selected_config = network_configs.get(network_type, network_configs['bridge'])
selected_network = create_network(selected_config)

# Provision the VMs
base_volume_name = get_base_volume()
cloud_init_disks = [create_cloud_init_disk(i) for i in range(num_vms)]
volumes = [create_volume(i, base_volume_name) for i in range(num_vms)]
vms = [create_vm(i, cloud_init_disks[i], volumes[i], selected_network) for i in range(num_vms)]

# Export network and VM information
pulumi.export("selected_network_name", selected_network.name)
pulumi.export("network_type", network_type)
pulumi.export("vm_ips", [vm.network_interfaces[0]["network_name"] for vm in vms])
