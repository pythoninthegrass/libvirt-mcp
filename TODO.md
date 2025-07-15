# TODO

* Test on linux
* Networking
  * dhcp
  * static

> To change VMs to bridge mode, you would typically need to:
> 
> Create a bridge network - Define a new libvirt network that uses bridge mode instead of NAT
> Modify VM network interfaces - Update each VM's configuration to use the bridge network
> Restart VMs - Apply the network changes
> 
> This usually requires direct access to libvirt commands like:
> 
> virsh net-define (to create bridge networks)
> virsh edit <vm-name> (to modify VM network configurations)
> virsh attach-interface or virsh detach-interface (to change network interfaces)

* Current limitations

> The libvirt-mcp create_vm function only creates basic VMs with default networking and storage. It can't recreate:
> 
> * Custom networks
> * Backing store relationships
> * Cloud-init configurations
> * Specific MAC addresses
> * SPICE console ports
> 
> To fully reconstruct the original VMs, you would need to:
> 
> 1. Use Terraform again (recommended) - rerun your original Terraform configuration
> 2. Use virsh commands manually to recreate the complex storage volumes and network setup
> 3. Accept basic VMs with the simple create_vm function (different from originals)

* Write tests
* Add task runners
