from pathlib import Path


def build_mcp_config(user_data_dir: Path) -> dict:
    """MCP servers for the apply agent: Playwright (persistent browser
    profile so logins survive across jobs) and Gmail (OTP retrieval during
    per-employer account signup -- see TECH_REQUIREMENT.md)."""
    return {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp@latest",
                    f"--user-data-dir={user_data_dir}",
                ],
            },
            "gmail": {
                "command": "npx",
                "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
            },
        }
    }
