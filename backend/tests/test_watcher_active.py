"""
Tests that the watcher only watches active, non-deleted instruments and stops watching
one that is set to inactive or deleted.

Run inside the backend container:
    docker exec fastapi_gateway_backend python -m pytest tests -q
"""
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # noqa: F401 — registers all models
from db.base_class import Base
from db.models.sequencers import Sequencers
from services import watcher


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(watcher, "SESSION_LOCAL", factory)
    return factory


def add_instrument(db, name, **kw):
    s = Sequencers(name=name, slug=name, location=f"/runs/{name}", **kw)
    db.add(s)
    db.commit()
    return s


def test_query_returns_only_active_instruments(session_factory):
    db = session_factory()
    add_instrument(db, "on", status="active")
    add_instrument(db, "off", status="inactive")
    add_instrument(db, "gone", status="active", is_deleted=True)
    db.close()

    assert [s.name for s in watcher.query_sequencers()] == ["on"]
    assert [s.name for s in watcher.load_sequencers()] == ["on"]


def test_query_error_returns_none(monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(watcher, "SESSION_LOCAL", lambda: SimpleNamespace(query=lambda *a: broken(), close=lambda: None))
    assert watcher.query_sequencers() is None


class FakeObserver:
    def __init__(self):
        self.unscheduled = []

    def unschedule(self, watch):
        self.unscheduled.append(watch)


def test_unwatch_stops_instruments_no_longer_listed():
    keep, drop = str(uuid4()), str(uuid4())
    watched = {keep: "watch-keep", drop: "watch-drop"}
    tracker = {keep: {}, drop: {"run": 1}}
    observer = FakeObserver()

    watcher.unwatch_gone_sequencers([SimpleNamespace(uuid=keep)], observer, watched, tracker)

    assert observer.unscheduled == ["watch-drop"]
    assert watched == {keep: "watch-keep"}
    assert drop not in tracker
