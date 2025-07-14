# Libvirt Ubuntu VM Cluster - Pulumi Quickstart

This guide will help you deploy a cluster of Ubuntu VMs using Pulumi and libvirt. The infrastructure creates a custom network and multiple Ubuntu VMs with cloud-init configuration, ready for Ansible automation.

## Prerequisites

### System Requirements

- Linux host with KVM/QEMU virtualization support
- libvirt daemon installed and running
- Python 3.11+ installed
- Pulumi CLI installed

### Install Required Software

#### 1. Install Pulumi CLI

```bash
# Linux/macOS
curl -fsSL https://get.pulumi.com | sh

# Or using package managers
# Ubuntu/Debian
curl -fsSL https://get.pulumi.com | sh && sudo mv ~/.pulumi/bin/pulumi /usr/local/bin/

# Add to PATH
export PATH=$PATH:~/.pulumi/bin
```

#### 2. Install libvirt and KVM

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virt-manager

# CentOS/RHEL/Fedora
sudo dnf install qemu-kvm libvirt virt-install virt-viewer bridge-utils

# Start and enable libvirt
sudo systemctl start libvirtd
sudo systemctl enable libvirtd

# Add your user to libvirt group
sudo usermod -a -G libvirt $USER
# Log out and back in for group changes to take effect
```

#### 3. Verify libvirt Installation

```bash
# Test libvirt connection
virsh list --all

# Check default storage pool exists
virsh pool-list --all

# If default pool doesn't exist, create it
sudo virsh pool-define-as default dir --target /var/lib/libvirt/images
sudo virsh pool-start default
sudo virsh pool-autostart default
```

#### 4. Configure AppArmor (Ubuntu/Debian)

On Ubuntu systems, AppArmor may restrict libvirt access to disk images:

```bash
# Check if AppArmor is active
sudo aa-status

# Pre-configure libvirt AppArmor profile for custom image paths
sudo nano /etc/apparmor.d/abstractions/libvirt-qemu
# Ensure these lines are present:
# /var/lib/libvirt/images/** rwk,
# /var/lib/libvirt/images-*/** rwk,

# Reload AppArmor profiles
sudo systemctl reload apparmor
```

## Project Setup

### 1. Initialize New Pulumi Project

```bash
# Create and navigate to project directory
mkdir libvirt-vm-cluster
cd libvirt-vm-cluster

# Initialize Pulumi project
pulumi new python --name libvirt-vms --description "libvirt vm ubuntu cluster"
```

### 2. Configure Python Runtime

Edit `Pulumi.yaml` to match the provided configuration:
```yaml
name: libvirt-vms
description: libvirt vm ubuntu cluster
runtime:
  name: python
  options:
    toolchain: uv
config:
  pulumi:tags:
    value:
      pulumi:template: python
packages:
  libvirt:
    source: terraform-provider
    version: 0.12.0
    parameters:
      - dmacvicar/libvirt
```

### 3. Install Dependencies

```bash
# Install the libvirt provider package
pulumi package add terraform-provider dmacvicar/libvirt

# If using uv (recommended)
uv add pulumi pulumi-libvirt

# If using pip
pip install pulumi pulumi-libvirt
```

### 4. Replace Main Code

Replace the contents of `__main__.py` with the provided code from your documents.

## Configuration

### Configure Libvirt Connection

Set the libvirt connection URI:
```bash
# For local libvirt (most common)
export LIBVIRT_DEFAULT_URI="qemu:///system"

# Or configure in Pulumi
pulumi config set libvirt:uri "qemu:///system"
```

### Optional Configuration Parameters

You can customize the deployment by setting these configuration values:

```bash
# Number of VMs to create (default: 3)
pulumi config set vm_count 5

# Memory per VM in MB (default: 2048)
pulumi config set vm_memory 4096

# Number of vCPUs per VM (default: 2)
pulumi config set vm_vcpus 4

# Base IP address range (default: 192.168.100)
pulumi config set base_ip "192.168.100"

# Ubuntu image URL (optional - uses latest Jammy by default)
pulumi config set ubuntu_image_url "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"
```

## Deployment

### 1. Preview the Infrastructure

```bash
pulumi preview
```

### 2. Deploy the Infrastructure

```bash
pulumi up
```

### 3. View Deployment Information

```bash
# See all stack outputs
pulumi stack output

# Get specific information
pulumi stack output vms
pulumi stack output ssh_commands
pulumi stack output ansible_inventory
```

## Accessing Your VMs

### SSH Access

The VMs are configured with the `ubuntu` user and passwordless sudo. SSH keys need to be added manually or through cloud-init configuration.

```bash
# Example SSH commands (from stack output)
ssh ubuntu@192.168.100.10
ssh ubuntu@192.168.100.11
ssh ubuntu@192.168.100.12
```

### Adding SSH Keys

To add your SSH key to the VMs, you can either:

1. **Modify the cloud-init configuration** in `__main__.py`:

```python
def create_user_data():
    user_data = dedent(f"""#cloud-config
    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        shell: /bin/bash
        lock_passwd: true
        ssh_authorized_keys:
          - {your_public_key_here}
    # ... rest of config
    """)

2. **Use console access** to add keys after deployment:

```bash
# Access VM console
sudo virsh console ubuntu-vm-1

# Or use virt-manager GUI
virt-manager
```

## Using with Ansible

The stack outputs an Ansible inventory that you can use directly:

```bash
# Save the inventory to a file
pulumi stack output ansible_inventory > inventory.ini

# Test Ansible connectivity
ansible all -i inventory.ini -m ping

# Run Ansible playbooks
ansible-playbook -i inventory.ini your-playbook.yml
```

## Network Configuration

The deployment creates:

- **Network**: `pulumi-vm-network` (192.168.100.0/24)
- **DHCP**: Enabled with static IP assignments
- **DNS**: Enabled for local resolution
- **NAT**: Enabled for internet access

VM IP assignments:

- VM 1: 192.168.100.10
- VM 2: 192.168.100.11
- VM 3: 192.168.100.12
- And so on...

## Troubleshooting

### Common Issues

#### Permission Denied

```bash
# Ensure user is in libvirt group
groups $USER
# Should show libvirt group

# If not, add user and restart session
sudo usermod -a -G libvirt $USER
```

#### Storage Pool Issues

```bash
# Check storage pools
virsh pool-list --all

# Refresh default pool
sudo virsh pool-refresh default
```

#### Network Conflicts

```bash
# Check existing networks
virsh net-list --all

# If IP range conflicts, change base_ip config
pulumi config set base_ip "192.168.200"
```

#### VM Console Access

```bash
# Access VM console for debugging
sudo virsh console ubuntu-vm-1

# Exit console with Ctrl+]
```

#### AppArmor Blocking libvirt

AppArmor can prevent libvirt from accessing disk images or other resources:

```bash
# Check for AppArmor denials
sudo dmesg | grep -i apparmor | grep -i denied

# Check AppArmor status
sudo aa-status

# View current libvirt AppArmor profile
sudo cat /etc/apparmor.d/usr.sbin.libvirtd

# Common fix: Add custom image paths to AppArmor profile
sudo vim /etc/apparmor.d/abstractions/libvirt-qemu
# Add your custom paths, for example:
# /var/lib/libvirt/images-*/** rwk,
# /path/to/your/images/** rwk,

# Alternative: Temporarily disable AppArmor for testing (not recommended for production)
sudo systemctl stop apparmor
sudo systemctl disable apparmor

# Reload AppArmor after profile changes
sudo systemctl reload apparmor

# Restart libvirtd if needed
sudo systemctl restart libvirtd
```

### Debugging Cloud-init

```bash
# Check cloud-init status on VM
sudo cloud-init status

# View cloud-init logs
sudo journalctl -u cloud-init
sudo cat /var/log/cloud-init-output.log
```

## Cleanup

To destroy all resources:
```bash
pulumi destroy
```

This will remove all VMs, networks, and volumes created by the stack.

## What's Included

This deployment provides:

- ✅ Ubuntu 22.04 LTS (Jammy) VMs
- ✅ Custom NAT network with DNS
- ✅ Static IP assignments
- ✅ Cloud-init configuration
- ✅ Ansible pre-installed
- ✅ SSH server configured
- ✅ Passwordless sudo for ubuntu user
- ✅ Auto-start on host boot
- ✅ SPICE graphics for console access

## Next Steps

1. **Add SSH keys** to access VMs
2. **Create Ansible playbooks** for configuration management
3. **Set up monitoring** and logging
4. **Configure backups** for important data
5. **Scale the cluster** by adjusting `vm_count`

For more advanced configurations, refer to the [Pulumi libvirt provider documentation](https://www.pulumi.com/registry/packages/libvirt/) and [libvirt documentation](https://libvirt.org/docs.html).
