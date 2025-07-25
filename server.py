from handlers import register_handlers
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("libvirt-mcp-demo")

register_handlers(mcp)


def main():
    print("Hello from libvirt-mcp-demo!")


if __name__ == "__main__":
    mcp.run(transport="stdio")
