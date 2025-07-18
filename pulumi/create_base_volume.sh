#!/usr/bin/env bash

# shellcheck disable=SC2046,SC2086

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Set defaults
BASE_IMAGE_NAME=${BASE_IMAGE_NAME:-"ubuntu-base-volume"}
BASE_IMAGE_PATH=${BASE_IMAGE_PATH:-"/data/libvirt/images/ubuntu-24.04-base.qcow2"}
STORAGE_POOL=${STORAGE_POOL:-"default"}
IMAGE_FORMAT=${IMAGE_FORMAT:-"qcow2"}
LIBVIRT_DEFAULT_URI=${LIBVIRT_DEFAULT_URI:-"qemu:///system"}

# Extract host from URI if it's a remote connection
if [[ $LIBVIRT_DEFAULT_URI == *"ssh://"* ]]; then
    HOST=$(echo $LIBVIRT_DEFAULT_URI | sed -n 's/.*ssh:\/\/\([^@]*@\)\?\([^\/]*\)\/.*/\2/p')
    if [[ $HOST == *"@"* ]]; then
        HOST=$(echo $HOST | cut -d'@' -f2)
    fi
    SSH_PREFIX="ssh $HOST"
else
    SSH_PREFIX=""
fi

cat <<EOF
Creating base volume with:
	Libvirt URI:     $LIBVIRT_DEFAULT_URI
	Base image name: $BASE_IMAGE_NAME
	Base image path: $BASE_IMAGE_PATH
	Storage pool:    $STORAGE_POOL
	Image format:    $IMAGE_FORMAT
EOF

# Create the base volume
CMD="sudo virsh vol-create-as $STORAGE_POOL $BASE_IMAGE_NAME 0 --format $IMAGE_FORMAT --backing-vol $BASE_IMAGE_PATH --backing-vol-format $IMAGE_FORMAT"

# Execute command and check exit status directly
if [ -n "$SSH_PREFIX" ]; then
    echo "Running: $SSH_PREFIX \"$CMD\""
    if $SSH_PREFIX "$CMD"; then
        echo "✅ Base volume '$BASE_IMAGE_NAME' created successfully"
    else
        echo "❌ Failed to create base volume"
    fi
else
    echo "Running: $CMD"
    if $CMD; then
        echo "✅ Base volume '$BASE_IMAGE_NAME' created successfully"
    else
        echo "❌ Failed to create base volume"
    fi
fi
