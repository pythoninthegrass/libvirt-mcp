# TODO

* Test on linux
* Test via ssh
  * Set `LIBVIRT_DEFAULT_URI`
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

* Write tests
* Generate iac
  * tf
  * pulumi
* Add task runners
