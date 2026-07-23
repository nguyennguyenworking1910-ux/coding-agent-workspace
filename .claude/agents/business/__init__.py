"""Business Department - Sales operations and data management agents."""

from .group_sale_manager import GroupSaleManagerAgent

__all__ = [
    "GroupSaleManagerAgent",
]

# Business agents registry
BUSINESS_AGENTS = {
    "group_sale_manager": GroupSaleManagerAgent,
}

def get_business_agent(name: str):
    """Get a business department agent by name."""
    return BUSINESS_AGENTS.get(name)

def list_business_agents():
    """List all business department agents."""
    return list(BUSINESS_AGENTS.keys())
