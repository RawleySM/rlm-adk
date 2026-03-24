"""About subgroup — Drive account info and quota."""

from __future__ import annotations

import json as json_mod
from typing import Annotated

import typer

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    human_size,
    print_panel,
    should_use_json,
)

app = typer.Typer(help="About — Drive account info and storage quota.")


@app.callback(invoke_without_command=True)
def about(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Show Drive account info: user, storage quota, file count."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    info = service.about().get(fields="user,storageQuota").execute()
    user = info.get("user", {})
    quota = info.get("storageQuota", {})

    if json_mode:
        print(json_mod.dumps(info))
    else:
        usage = int(quota.get("usage", 0))
        limit = int(quota.get("limit", 0))
        data = {
            "Email": user.get("emailAddress", "—"),
            "Display Name": user.get("displayName", "—"),
            "Storage Used": human_size(usage),
            "Storage Limit": human_size(limit) if limit else "Unlimited",
            "Usage %": f"{usage / limit * 100:.1f}%" if limit else "—",
        }
        print_panel(data, "Google Drive Account", json_mode)


@app.command("quota")
def quota(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Detailed storage quota breakdown."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    info = service.about().get(fields="storageQuota").execute()
    quota_data = info.get("storageQuota", {})

    if json_mode:
        print(json_mod.dumps(quota_data))
    else:
        data = {
            "Total Usage": human_size(quota_data.get("usage", 0)),
            "Usage in Drive": human_size(quota_data.get("usageInDrive", 0)),
            "Usage in Trash": human_size(quota_data.get("usageInDriveTrash", 0)),
            "Storage Limit": human_size(quota_data.get("limit", 0)) if quota_data.get("limit") else "Unlimited",
        }
        print_panel(data, "Storage Quota", json_mode)
