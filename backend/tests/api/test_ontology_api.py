"""Object explorer: search, profiles with links, and the link graph."""
import pytest

from app.db.demo_contested import TASKS, seed_contested_scenario
from app.models.all_models import User


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def test_search_finds_every_kind(client, contested, viewer_headers):
    res = client.get(f"/api/v1/ontology/{contested}/search", headers=viewer_headers).json()
    kinds = {o["type"] for o in res}
    assert kinds == {"aircraft", "task", "site", "capability"}
    assert sum(o["type"] == "task" for o in res) == len(TASKS)

    night = client.get(f"/api/v1/ontology/{contested}/search?q=night", headers=viewer_headers).json()
    cap = next(o for o in night if o["type"] == "capability")
    assert cap["status"] == "SINGLE_POINT"  # only C-130-Alpha is night qualified


def test_profiles_link_objects(client, contested, viewer_headers):
    tasks = client.get(f"/api/v1/ontology/{contested}/search?type=task&q=WL-01", headers=viewer_headers).json()
    task = client.get(f"/api/v1/ontology/{contested}/objects/task/{tasks[0]['id']}", headers=viewer_headers).json()
    relations = {link["relation"] for link in task["links"]}
    assert {"flown by", "at site", "requires"} <= relations

    aircraft_id = next(l["id"] for l in task["links"] if l["relation"] == "flown by")
    aircraft = client.get(f"/api/v1/ontology/{contested}/objects/aircraft/{aircraft_id}", headers=viewer_headers).json()
    assert any(l["id"] == tasks[0]["id"] and l["relation"] == "flies" for l in aircraft["links"])

    site_id = next(l["id"] for l in task["links"] if l["relation"] == "at site")
    site = client.get(f"/api/v1/ontology/{contested}/objects/site/{site_id}", headers=viewer_headers).json()
    assert any(l["id"] == tasks[0]["id"] for l in site["links"])

    cap = client.get(f"/api/v1/ontology/{contested}/objects/capability/NIGHT_OPS", headers=viewer_headers).json()
    assert cap["properties"]["Single point of failure"] == "yes"


def test_graph_edges_reference_nodes(client, contested, viewer_headers):
    g = client.get(f"/api/v1/ontology/{contested}/graph", headers=viewer_headers).json()
    keys = {n["key"] for n in g["nodes"]}
    assert g["edges"] and all(e["source"] in keys and e["target"] in keys for e in g["edges"])
    flies = [e for e in g["edges"] if e["relation"] == "flies"]
    assert len(flies) == len(TASKS)  # every task has an aircraft in the seeded baseline


def test_unknown_object_is_404(client, contested, viewer_headers):
    assert client.get(f"/api/v1/ontology/{contested}/objects/aircraft/nope", headers=viewer_headers).status_code == 404
