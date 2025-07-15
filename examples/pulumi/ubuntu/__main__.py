#!/usr/bin/env python

import base64
import pulumi
import pulumi_libvirt as libvirt
from decouple import config
from textwrap import dedent

# env vars
LIBVIRT_DEFAULT_URI = config("LIBVIRT_DEFAULT_URI", default="qemu:///system")
BASE_IP = config("BASE_IP", default="192.168.200")
UBUNTU_IMAGE_PATH = config("UBUNTU_IMAGE_PATH", default=None)
UBUNTU_IMAGE_URL = config("UBUNTU_IMAGE_URL",
                          default="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img")
VM_COUNT = config("VM_COUNT", default=3, cast=int)
VM_CPU = config("VM_CPU", default=2, cast=int)
VM_RAM = config("VM_RAM", default=2048, cast=int)
VM_SIZE_GB = config("VM_SIZE_GB", default=32, cast=int)
VM_SIZE_BYTES = VM_SIZE_GB * 1024 * 1024 * 1024

# configuration
conf = pulumi.Config()
vm_count = conf.get_int("vm_count") or VM_COUNT
vm_vcpus = conf.get_int("vm_vcpus") or VM_CPU
vm_memory = conf.get_int("vm_memory") or VM_RAM
base_ip = conf.get("base_ip") or BASE_IP
ubuntu_image_path = conf.get("ubuntu_image_path") or UBUNTU_IMAGE_PATH
ubuntu_image_url = conf.get("ubuntu_image_url") or UBUNTU_IMAGE_URL

# Use URL source to avoid path issues with remote libvirt
image_source = ubuntu_image_url

print(f"Using image source: {image_source}")

# create a custom network for the vms
vm_network = libvirt.Network(
    "vm-network",
    name="pulumi-vm-network",
    mode="nat",
    domain="vm.local",
    addresses=[f"{base_ip}.0/24"],
    dns={
        "enabled": True,
        "local_only": False,
    },
    dhcp={
        "enabled": True,
    },
)

# create base ubuntu image volume using predownloaded image
base_volume = libvirt.Volume(
    "ubuntu-base",
    name="ubuntu-noble-base",
    source=image_source,  # Use configured image source
    format="qcow2",
    pool="default"
)


# cloud-init user data template
def create_user_data():
    user_data = dedent("""\
    #cloud-config

    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        shell: /bin/bash
        lock_passwd: true
        ssh_import_id:
          - gh:pythoninthegrass

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


# network data template for static ip
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


# create vms
vms = []
for i in range(vm_count):
    vm_name = f"ubuntu-vm-{i + 1}"
    static_ip = f"{base_ip}.{10 + i}"

    # create volume for this vm (copy of base)
    vm_volume = libvirt.Volume(
        f"volume-{i + 1}",
        name=f"ubuntu-vm-{i + 1}-disk",
        base_volume_id=base_volume.id,
        format="qcow2",
        size=VM_SIZE_BYTES,
        pool="default",
        # Explicit dependency on base volume
        opts=pulumi.ResourceOptions(depends_on=[base_volume]),
    )

    cloudinit_disk = libvirt.CloudInitDisk(
        f"cloudinit-{i + 1}",
        name=f"cloudinit-{i + 1}.iso",
        user_data=create_user_data(),
        network_config=create_network_data(static_ip),
        pool="default",
    )

    # create the vm domain - CRITICAL: Depend on ALL prerequisites
    vm = libvirt.Domain(
        f"vm-{i + 1}",
        name=vm_name,
        memory=vm_memory,
        vcpu=vm_vcpus,
        # network interface
        network_interfaces=[
            {
                "network_id": vm_network.id,
                "hostname": vm_name,
                "addresses": [static_ip],
                "wait_for_lease": True,
            }
        ],
        # disks
        disks=[
            {
                "volume_id": vm_volume.id,
            },
        ],
        # Cloud-init disk reference
        cloudinit=cloudinit_disk.id,
        # CRITICAL: Explicit dependencies on ALL required resources
        opts=pulumi.ResourceOptions(
            depends_on=[
                vm_network,  # Network must be ready
                vm_volume,  # VM disk must be ready
                cloudinit_disk,  # CloudInit disk must be ready
                base_volume,  # Base volume must be ready
            ]
        ),
        # console access
        consoles=[
            {
                "type": "pty",
                "target_port": "0",
                "target_type": "serial",
            }
        ],
        # graphics (spice)
        graphics={
            "type": "spice",
            "listen_type": "address",
            "listen_address": "127.0.0.1",
            "autoport": True,
        },
        # machine type
        machine="pc",
        arch="x86_64",
        # auto-start on boot
        autostart=True,
    )

    vms.append(vm)

# export important information
pulumi.export("network_name", vm_network.name)
pulumi.export("network_bridge", vm_network.bridge)

# export vm information
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

# export connection commands
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
