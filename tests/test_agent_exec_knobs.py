"""Phase 7-live follow-up: the agent_exec_* knobs are exposed on CLI / SDK / endpoint surfaces."""

from __future__ import annotations

import argparse

from rogue.cli import _agent_exec_kwargs, _tools_list
from rogue.client import Client
from rogue.reproduce.endpoint_scan import make_endpoint_config


def test_sdk_client_tools_reach_the_config():
    c = Client(endpoint="https://x/v1", tools=["web_fetch", "read_file"], forbidden_tools=["send_email"])
    assert c.config.declared_tools == ["web_fetch", "read_file"]
    assert c.config.forbidden_tools == ["send_email"]


def test_make_endpoint_config_declares_tools():
    cfg = make_endpoint_config("https://x/v1", "my-model", declared_tools=["web_fetch"], forbidden_tools=["send_email"])
    assert cfg.declared_tools == ["web_fetch"]
    assert cfg.forbidden_tools == ["send_email"]


def test_cli_tools_list_parses_comma_separated():
    assert _tools_list(argparse.Namespace(tools="web_fetch, read_file ,send_email")) == ["web_fetch", "read_file", "send_email"]
    assert _tools_list(argparse.Namespace(tools=None)) is None
    assert _tools_list(argparse.Namespace(tools=None), {"tools": ["a", "b"]}) == ["a", "b"]


def test_cli_agent_exec_kwargs():
    a = argparse.Namespace(no_agent_exec=False, agent_exec_seeds=5, agent_exec_stress=True)
    assert _agent_exec_kwargs(a) == {"agent_exec": True, "agent_exec_seeds": 5, "agent_exec_framing": "amplified"}
    b = argparse.Namespace(no_agent_exec=True, agent_exec_seeds=None, agent_exec_stress=False)
    assert _agent_exec_kwargs(b) == {"agent_exec": False, "agent_exec_seeds": 3, "agent_exec_framing": "raw"}
