"""Editing action items after extraction: check off, correct, add, delete."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import MeetingRepository, NotesNotReadyError
from app.schemas import MeetingNotes, StoredNotes

from .conftest import MEETING_DATE, sample_notes, short_transcript, wait_done


def _completed(client: TestClient) -> tuple[str, list[dict[str, Any]]]:
    r = client.post("/api/meetings/transcript", json={"text": "Ana: Ben, send the report by Friday."})
    mid = r.json()["id"]
    wait_done(client)
    items = client.get(f"/api/meetings/{mid}").json()["notes"]["action_items"]
    return mid, items


def _url(mid: str, item_id: str | None = None) -> str:
    base = f"/api/meetings/{mid}/action-items"
    return f"{base}/{item_id}" if item_id else base


def test_items_have_unique_stable_ids(client: TestClient) -> None:
    mid, items = _completed(client)
    ids = [i["id"] for i in items]
    assert len(set(ids)) == len(ids) == 2
    again = client.get(f"/api/meetings/{mid}").json()["notes"]["action_items"]
    assert [i["id"] for i in again] == ids
    assert all(i["done"] is False and i["edited"] is False for i in items)


def test_check_off_does_not_mark_edited(client: TestClient) -> None:
    mid, items = _completed(client)
    r = client.patch(_url(mid, items[0]["id"]), json={"done": True})
    assert r.status_code == 200
    assert r.json()["done"] is True
    assert r.json()["edited"] is False
    stored = client.get(f"/api/meetings/{mid}").json()["notes"]["action_items"]
    assert stored[0]["done"] is True
    assert stored[1]["done"] is False
    md = client.get(f"/api/meetings/{mid}/markdown").text
    assert "| x | Finish the payments SDK upgrade |" in md


def test_correct_owner_and_due_date(client: TestClient) -> None:
    mid, items = _completed(client)
    r = client.patch(
        _url(mid, items[1]["id"]), json={"owner": "  Priya ", "due_date": "2026-12-01", "priority": "high"}
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["owner"], body["due_date"], body["priority"]) == ("Priya", "2026-12-01", "high")
    assert body["edited"] is True
    assert body["task"] == items[1]["task"]  # untouched fields are kept
    assert body["id"] == items[1]["id"]


def test_null_clears_owner_and_date(client: TestClient) -> None:
    mid, items = _completed(client)
    body = client.patch(_url(mid, items[0]["id"]), json={"owner": None, "due_date": None}).json()
    assert body["owner"] is None
    assert body["due_date"] is None
    assert body["edited"] is True


def test_patch_with_same_values_is_not_an_edit(client: TestClient) -> None:
    mid, items = _completed(client)
    body = client.patch(_url(mid, items[0]["id"]), json={"owner": items[0]["owner"]}).json()
    assert body["edited"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"task": None},
        {"task": ""},
        {"done": None},
        {"priority": "urgent"},
        {"due_date": "next friday"},
        {"id": "hijack"},
        {"edited": False},
    ],
)
def test_invalid_patches_are_rejected(client: TestClient, payload: dict[str, Any]) -> None:
    mid, items = _completed(client)
    r = client.patch(_url(mid, items[0]["id"]), json=payload)
    assert r.status_code == 422
    assert client.get(f"/api/meetings/{mid}").json()["notes"]["action_items"] == items


def test_unknown_meeting_and_item_are_404(client: TestClient) -> None:
    mid, _ = _completed(client)
    assert client.patch(_url(mid, "nope"), json={"done": True}).status_code == 404
    assert client.patch(_url("missing", "nope"), json={"done": True}).status_code == 404
    assert client.delete(_url(mid, "nope")).status_code == 404
    assert client.post(_url("missing"), json={"task": "x"}).status_code == 404


def test_add_and_delete_items(client: TestClient) -> None:
    mid, items = _completed(client)
    r = client.post(_url(mid), json={"task": "Book a retro", "owner": "Ana", "due_date": "2026-12-02"})
    assert r.status_code == 201
    new = r.json()
    assert new["edited"] is True
    assert new["done"] is False
    assert new["priority"] == "medium"
    assert new["timestamp_s"] is None
    assert new["id"] not in {i["id"] for i in items}

    stored = client.get(f"/api/meetings/{mid}").json()["notes"]["action_items"]
    assert [i["id"] for i in stored] == [*(i["id"] for i in items), new["id"]]

    assert client.delete(_url(mid, items[0]["id"])).status_code == 204
    stored = client.get(f"/api/meetings/{mid}").json()["notes"]["action_items"]
    assert [i["id"] for i in stored] == [items[1]["id"], new["id"]]


def test_add_rejects_bad_body(client: TestClient) -> None:
    mid, _ = _completed(client)
    assert client.post(_url(mid), json={"task": ""}).status_code == 422
    assert client.post(_url(mid), json={"task": "x", "done": True}).status_code == 422


def test_editing_before_notes_exist_is_409(repo: MeetingRepository, client: TestClient) -> None:
    pending = client.app.state.container.repo.create(  # type: ignore[attr-defined]
        filename="x.txt", meeting_date=MEETING_DATE, transcript=short_transcript()
    )
    assert client.patch(_url(pending.id, "item-0"), json={"done": True}).status_code == 409
    assert client.post(_url(pending.id), json={"task": "x"}).status_code == 409


def test_concurrent_edits_are_not_lost(repo: MeetingRepository) -> None:
    m = repo.create(filename="x.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    repo.save_notes(m.id, MeetingNotes(title="t", summary="s"))

    def add(n: int) -> None:
        def mutate(notes: StoredNotes) -> None:
            notes.action_items.append(
                StoredNotes.model_validate(
                    {"title": "t", "summary": "s", "action_items": [{"task": f"t{n}"}]}
                )
                .action_items[0]
                .model_copy(update={"id": f"x{n}"})
            )

        repo.update_notes(m.id, mutate)

    threads = [threading.Thread(target=add, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    detail = repo.get(m.id)
    assert detail is not None
    assert detail.notes is not None
    assert sorted(i.id for i in detail.notes.action_items) == sorted(f"x{n}" for n in range(20))


def test_update_notes_errors(repo: MeetingRepository) -> None:
    with pytest.raises(KeyError):
        repo.update_notes("missing", lambda n: None)
    m = repo.create(filename="x.txt", meeting_date=MEETING_DATE, transcript=short_transcript())
    with pytest.raises(NotesNotReadyError):
        repo.update_notes(m.id, lambda n: None)


def test_legacy_rows_without_ids_get_stable_positional_ids() -> None:
    raw = sample_notes().model_dump(mode="json")
    a = StoredNotes.model_validate(raw)
    b = StoredNotes.model_validate(raw)
    assert [i.id for i in a.action_items] == ["item-0", "item-1"] == [i.id for i in b.action_items]


def test_from_extracted_assigns_fresh_ids() -> None:
    a = StoredNotes.from_extracted(sample_notes())
    b = StoredNotes.from_extracted(sample_notes())
    assert {i.id for i in a.action_items}.isdisjoint({i.id for i in b.action_items})


def test_claude_schema_has_no_tracking_fields() -> None:
    props = MeetingNotes.model_json_schema()["$defs"]["ActionItem"]["properties"]
    assert not {"id", "done", "edited"} & set(props)
