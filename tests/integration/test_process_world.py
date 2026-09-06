"""Loopback process-world lifecycle and fresh-reset integration coverage."""

from pathlib import Path

import httpx
from domains.confluence.world.fixtures.builder import build_store

from agentgym.core.scenario import write_snapshot
from agentgym.world.process import ProcessWorldProvider


async def test_process_world_control_and_fresh_world_reset(tmp_path: Path) -> None:
    store = build_store(seed=1100)
    snapshot_path = write_snapshot(
        store.snapshot(snapshot_id="fixture", timestamp="2026-09-06T00:00:00+00:00"),
        tmp_path / "snapshots" / "fixture.json",
    )

    provider = ProcessWorldProvider(snapshot_path)
    await provider.start()
    try:
        async with httpx.AsyncClient(
            base_url=provider.base_url,
            trust_env=False,
        ) as client:
            page = await client.get("/api/pages/page-1", headers={"X-Actor": "alice"})
            assert page.status_code == 200
            assert page.json()["version"] == 1

            human = await client.post(
                "/api/control/human-edit",
                headers={"X-Control-Key": provider.control_key},
                json={
                    "page_id": "page-1",
                    "actor": "human-editor",
                    "body": "A human edit",
                },
            )
            assert human.status_code == 200
            assert human.json()["version"] == 2

            captured = await client.post(
                "/api/control/snapshot",
                headers={"X-Control-Key": provider.control_key},
            )
            assert captured.status_code == 200
            assert captured.json()["resources"]["pages"]["page-1"]["version"] == 2
    finally:
        await provider.stop()

    fresh_provider = ProcessWorldProvider(snapshot_path)
    await fresh_provider.start()
    try:
        fresh = await fresh_provider.snapshot()
        assert fresh.resources["pages"]["page-1"]["version"] == 1
        assert fresh.resources["pages"]["page-1"]["body"] == store.pages["page-1"]["body"]
    finally:
        await fresh_provider.stop()
