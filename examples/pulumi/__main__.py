#!/usr/bin/env python

import base64
import pulumi
import pulumi_libvirt as libvirt
from textwrap import dedent

# Configuration
config = pulumi.Config()
vm_count = config.get_int("vm_count") or 3
vm_memory = config.get_int("vm_memory") or 2048  # MB
vm_vcpus = config.get_int("vm_vcpus") or 2
base_ip = config.get("base_ip") or "192.168.200"
ubuntu_image_url = (
    config.get("ubuntu_image_url") or "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"
)

# Create a custom network for the VMs
vm_network = libvirt.Network(
    "vm-network",
    name="pulumi-vm-network",
    mode="nat",
    domain="vm.local",
    addresses=["192.168.200.0/24"],
    dns={
        "enabled": True,
        "local_only": False,
    },
    dhcp={
        "enabled": True,
    },
)

# Create base Ubuntu image volume
base_volume = libvirt.Volume("ubuntu-base",
                             name="ubuntu-jammy-base",
                             source=ubuntu_image_url,
                             format="qcow2",
                             pool="default")


# Cloud-init user data template
def create_user_data():
    user_data = dedent("""#cloud-config
    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        shell: /bin/bash
        lock_passwd: true
        ssh_authorized_keys: []

    package_update: true
    package_upgrade: true

    packages:
      - ansible
      - curl
      - git
      - openssh-server
      - python3-pip
      - wget

    runcmd:
      - systemctl enable ssh
      - systemctl start ssh
      - echo "Cloud-init setup complete" > /tmp/cloud-init-done

    final_message: "VM setup complete with ansible installed after $UPTIME seconds."
    """)
    return base64.b64encode(user_data.encode()).decode()


# Network data template for static IP
def create_network_data(ip_address):
    network_data = dedent(f"""
    version: 2
    ethernets:
      ens3:
        dhcp4: false
        addresses:
          - {ip_address}/24
        gateway4: 192.168.200.1
        nameservers:
          addresses:
            - 8.8.8.8
            - 8.8.4.4
    """)
    return base64.b64encode(network_data.encode()).decode()


# Create VMs
vms = []
for i in range(vm_count):
    vm_name = f"ubuntu-vm-{i + 1}"
    static_ip = f"{base_ip}.{10 + i}"

    # Create volume for this VM (copy of base)
    vm_volume = libvirt.Volume(
        f"volume-{i + 1}",
        name=f"ubuntu-vm-{i + 1}-disk",
        base_volume_id=base_volume.id,
        format="qcow2",
        size=34359738368,  # 32GB
        pool="default",
    )

    # Skip cloud-init for now
    # cloudinit_disk = libvirt.CloudinitDisk(
    #     f"cloudinit-{i + 1}",
    #     name=f"cloudinit-{i + 1}.iso",
    #     user_data=create_user_data(),
    #     network_config=create_network_data(static_ip),
    #     pool="default",
    # )

    # Create the VM domain
    vm = libvirt.Domain(
        f"vm-{i + 1}",
        name=vm_name,
        memory=vm_memory,
        vcpu=vm_vcpus,
        # Network interface
        network_interfaces=[
            {
                "network_id": vm_network.id,
                "hostname": vm_name,
                "addresses": [static_ip],
                "wait_for_lease": True,
            }
        ],
        # Disks
        disks=[
            {
                "volume_id": vm_volume.id,
            },
            # Skip cloud-init disk for now
            # {
            #     "volume_id": cloudinit_disk.id,
            # },
        ],
        # Console access
        consoles=[
            {
                "type": "pty",
                "target_port": "0",
                "target_type": "serial",
            }
        ],
        # Graphics (SPICE)
        graphics={
            "type": "spice",
            "listen_type": "address",
            "listen_address": "127.0.0.1",
            "autoport": True,
        },
        # Boot configuration
        boot_devices=[{"dev": "hd"}],
        # Machine type
        machine="pc",
        arch="x86_64",
        # Auto-start on boot
        autostart=True,
    )

    vms.append(vm)

# Export important information
pulumi.export("network_name", vm_network.name)
pulumi.export("network_bridge", vm_network.bridge)

# Export VM information
vm_info = []
for i, vm in enumerate(vms):
    vm_info.append(
        {
            "name": vm.name,
            "ip_address": f"{base_ip}.{10 + i}",
            "memory_mb": vm_memory,
            "vcpus": vm_vcpus,
        }
    )

pulumi.export("vms", vm_info)

# Export connection commands
connection_commands = []
for i in range(vm_count):
    ip = f"{base_ip}.{10 + i}"
    connection_commands.append(f"ssh ubuntu@{ip}")

pulumi.export("ssh_commands", connection_commands)
pulumi.export(
    "ansible_inventory",
    pulumi.Output.all(*[vm.name for vm in vms]).apply(
        lambda names: "\n".join([f"{name} ansible_host={base_ip}.{10 + i} ansible_user=ubuntu" for i, name in enumerate(names)])
    ),
)
