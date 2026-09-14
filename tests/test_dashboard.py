from __future__ import annotations
import glob
import os
import pytest
import sqlalchemy
import pandas as pd
from sqlalchemy import create_engine as real_create_engine
from streamlit.testing.v1 import AppTest

# Monkeypatch pandas read_sql_query to unwrap MockConnectionWrapper to the real SQLAlchemy connection
orig_read_sql_query = pd.read_sql_query
def patched_read_sql_query(sql, con, *args, **kwargs):
    if hasattr(con, "conn"):
        con = con.conn
    return orig_read_sql_query(sql, con, *args, **kwargs)
pd.read_sql_query = patched_read_sql_query

class MockConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, statement, *args, **kwargs):
        sql_str = str(statement)
        if "AUTO_INCREMENT" in sql_str:
            sql_str = sql_str.replace("INTEGER AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY")
            sql_str = sql_str.replace("AUTO_INCREMENT", "")
            statement = sqlalchemy.text(sql_str)
        return self.conn.execute(statement, *args, **kwargs)

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        return self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getattr__(self, name):
        return getattr(self.conn, name)

class MockTransactionContext:
    def __init__(self, engine):
        self.engine = engine
        self.conn = None
        self.trans = None

    def __enter__(self):
        self.conn = self.engine.connect()
        self.trans = self.conn.begin()
        return MockConnectionWrapper(self.conn)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self.trans.rollback()
            else:
                self.trans.commit()
        finally:
            self.conn.close()

class MockEngineWrapper:
    def __init__(self, engine):
        self.engine = engine

    def begin(self):
        return MockTransactionContext(self.engine)

    def connect(self):
        return MockConnectionWrapper(self.engine.connect())

    def __getattr__(self, name):
        return getattr(self.engine, name)

def mock_create_engine(url, *args, **kwargs):
    if "cubrid" in str(url):
        engine = real_create_engine("sqlite:///:memory:", *args, **kwargs)
        return MockEngineWrapper(engine)
    return real_create_engine(url, *args, **kwargs)

sqlalchemy.create_engine = mock_create_engine

DASHBOARD_RECIPES = glob.glob("templates/dashboard/*.py")

@pytest.mark.parametrize("app_path", DASHBOARD_RECIPES)
def test_dashboard_recipe_runs_without_errors(app_path):
    """
    Test that each Streamlit dashboard recipe runs successfully 
    without throwing any UI exceptions using SQLite mock fallback.
    """
    abs_path = os.path.abspath(app_path)
    at = AppTest.from_file(abs_path)
    at.run()
    
    assert not at.exception, f"App '{app_path}' crashed with exception: {at.exception[0] if at.exception else 'Unknown Error'}"
