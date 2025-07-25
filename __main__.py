#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#    "jinja2>=3.1.6",
#    "libvirt-python>=11.3.0",
#    "mcp[cli]>=1.7.1",
#    "paramiko>=3.0.0",
#    "pulumi>=3.0.0,<4.0.0",
#    "pulumi-libvirt",
#    "python-decouple>=3.8",
#    "sh>=2.2.2",
# ]
# [tool.uv]
# exclude-newer = "2025-08-01T00:00:00Z"
# ///

# pyright: reportMissingImports=false

import pulumi
import pulumi_libvirt as libvirt
from config import (
    base_image_name,
    base_image_path,
    base_ip,
    gateway_ip,
    generate_cloud_init_with_static_ip,
    generate_network_config,
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
from decouple import config
from jinja2 import Environment, FileSystemLoader
from textwrap import dedent


def fetch_ssh_keys():
    """Fetch SSH keys once to avoid duplicate diagnostics."""
    from pathlib import Path

    # Read SSH public key
    ssh_public_key = ""
    try:
        ssh_key_path = Path.home() / ".ssh" / "id_rsa.pub"
        if ssh_key_path.exists():
            ssh_public_key = ssh_key_path.read_text().strip()
    except Exception as e:
        print(f"Warning: Could not read SSH public key: {e}")

    # Get GitHub username from config or use default
    github_ssh_user = config("GITHUB_SSH_USER", default="pythoninthegrass")

    # Collect all SSH keys (local + GitHub)
    all_ssh_keys = []
    if ssh_public_key:
        all_ssh_keys.append(ssh_public_key)

    # Fetch GitHub SSH keys if username is provided
    if github_ssh_user:
        try:
            import urllib.request

            with urllib.request.urlopen(f"https://github.com/{github_ssh_user}.keys") as response:
                github_keys = response.read().decode('utf-8').strip().split('\n')
                github_keys = [key.strip() for key in github_keys if key.strip()]
                all_ssh_keys.extend(github_keys)
                print(f"Fetched {len(github_keys)} GitHub SSH keys for {github_ssh_user}")
        except Exception as e:
            print(f"Warning: Failed to fetch GitHub SSH keys for {github_ssh_user}: {e}")

    return all_ssh_keys, github_ssh_user


def create_cloud_init_disk(vm_index, vm_name, all_ssh_keys=None, github_ssh_user=""):
    """Creates a cloud-init disk for the given VM index with static IP configuration."""
    use_jinja_templates = config("USE_JINJA_TEMPLATES", default=True, cast=bool)

    if use_jinja_templates:
        # Use the centralized cloud-init generation with static IP
        try:
            from pathlib import Path

            # Format SSH keys section for cloud-init with all keys
            ssh_keys_section = "ssh_authorized_keys:\n" + "\n".join(f"  - {key}" for key in all_ssh_keys) if all_ssh_keys else ""

            # Use the centralized template rendering with SSH keys
            template_path = Path(__file__).parent / "templates"
            env = Environment(loader=FileSystemLoader(template_path))
            template = env.get_template("cloud-init.yml.j2")

            cloud_init_config = template.render(
                username="ubuntu",
                password="ubuntu",
                groups=["sudo"],
                packages=["curl", "git", "openssh-server", "qemu-guest-agent", "wget"],
                dns_servers=["8.8.8.8", "8.8.4.4"],
                ssh_keys_section=ssh_keys_section,
                github_ssh_user=github_ssh_user,
                hostname=vm_name,
            )

            # Generate network configuration
            network_config = generate_network_config(vm_index)

        except Exception as e:
            # Fallback to simple config if template fails
            print(f"Warning: Failed to render Jinja2 template, falling back to simple config: {e}")
            use_jinja_templates = False

    if not use_jinja_templates:
        # Use simple cloud-init configuration (fallback)
        # fmt: off
        cloud_init_config = dedent("""
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
        """).strip()
        # fmt: on
        network_config = None

    return libvirt.CloudinitDisk(
        f"cloud-init-disk-{vm_index}",
        user_data=cloud_init_config,
        network_config=network_config,
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

    return libvirt.Volume(f"{vm_name_prefix}-{vm_index}-volume", **volume_args)


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
print(f"Base IP range: {get_static_ip(0)} - {get_static_ip(num_vms - 1) if num_vms > 1 else get_static_ip(0)}")
print(f"Base IP prefix: {base_ip}")
print(f"Gateway IP: {gateway_ip}")
print(f"Network CIDR: {network_cidr}")
print("===============================")

# Provision the VMs with static IPs
base_volume_name = get_base_volume()

# Fetch SSH keys once to avoid duplicate diagnostics
all_ssh_keys, github_ssh_user = fetch_ssh_keys()

static_ips = []
vms = []

for i in range(num_vms):
    vm_index = i
    vm_name = f"{vm_name_prefix}-{i + 1}"
    static_ip = get_static_ip(vm_index)
    static_ips.append(static_ip)

    # Create cloud-init disk with static IP configuration
    cloud_init_disk = create_cloud_init_disk(vm_index, vm_name, all_ssh_keys, github_ssh_user)

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
