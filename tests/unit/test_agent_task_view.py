"""Ground-truth isolation tests for the runtime task projection."""

from agentgym.core.task import Task
from agentgym.runtime.base import AgentTaskView, ToolDescription


def test_agent_task_view_contains_only_safe_task_and_tool_surface() -> None:
    task = Task(
        id="task-private",
        scenario_id="edit_page",
        split="test",
        goal="Update the page.",
        actor_id="alice",
        initial_snapshot_ref="snapshots/private.json",
        verifier_id="private-verifier",
        metadata={
            "verifier_config": {"expected_page_ids": ["page-1"]},
            "concurrency": {"human_edit": {"body": "private"}},
        },
    )
    view = AgentTaskView.from_task(
        task,
        [
            ToolDescription(
                name="get_page",
                description="Read a page.",
                parameters={"type": "object"},
            )
        ],
    )

    assert set(AgentTaskView.model_fields) == {"goal", "actor_id", "tools"}
    assert set(view.model_dump(mode="json")) == {"goal", "actor_id", "tools"}
    assert view.goal == task.goal
    assert view.actor_id == task.actor_id
    assert view.tool_names == ["get_page"]
    assert view.tool_descriptions == {"get_page": "Read a page."}
    assert not hasattr(view, "metadata")
    assert not hasattr(view, "verifier_config")
    assert not hasattr(view, "initial_snapshot_ref")
