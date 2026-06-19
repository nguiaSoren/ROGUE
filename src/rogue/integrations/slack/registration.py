"""Self-registration: a consented Slack agent becomes a ROGUE `DeploymentConfig`.

Build-area 06 §2. A customer who runs an LLM-backed Slack agent registers it with ROGUE
so the reproduction engine can continuously red-team *their deployed configuration* (model
× system prompt × tools), not a generic model. Because the agent is reached through an
OpenAI-compatible endpoint, the produced `DeploymentConfig` carries a `base_url` — which is
exactly what routes it through `CustomHTTPAdapter` (provider resolves to "custom" in
`target_panel`) instead of by model-id prefix. This mirrors the ad-hoc endpoint-scan path
(`rogue.reproduce.endpoint_scan.make_endpoint_config`); we do not duplicate adapter routing.

Effective-prompt note (v1): "pull the agent's effective system prompt/behavior" means the
customer SUPPLIES it at registration — they paste/export their agent's system prompt + tool
list. It is NOT obtained via Slack-API introspection: Slack exposes no API to read a
third-party bot's prompt (platform-permission limit). There is therefore NO Slack-scraping
code in this module; the functions here do field validation and config construction only.

Side-effect-free import: nothing here opens a DB connection or builds an engine at module
load. Persistence is injected (`agent_store`), and the agent-store ORM is imported lazily
inside `agent_store.py` methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rogue.schemas import DeploymentConfig

if TYPE_CHECKING:  # avoid an import cycle — agent_store imports this module's dataclass
    from .agent_store import SlackAgentStore as _SlackAgentStore


@runtime_checkable
class _AgentStoreLike(Protocol):
    """Duck-typed agent-store surface `register_slack_agent` needs (avoids importing
    agent_store.py at module top level)."""

    def put(self, target: "SlackAgentTarget") -> str: ...


@runtime_checkable
class _IntegrationStoreLike(Protocol):
    """Duck-typed integration-store surface for the optional Slack-app credential path."""

    def put(self, *, org_id: str, kind: str, name: str, config: dict, secret: str | None) -> str: ...


@dataclass(frozen=True)
class SlackAgentTarget:
    """A customer's consented Slack-agent self-registration.

    Frozen + hashable: `declared_tools` / `forbidden_topics` are tuples. Callers passing the
    natural `list[str]` should use `SlackAgentTarget.create(...)`, which normalizes to tuples.

    Fail-closed validation (`__post_init__`): `org_id`, `agent_name`, `workspace`, `base_url`,
    `model`, `sandbox_channel_id`, and `security_channel_id` are all mandatory and non-blank.
    The sandbox-channel binding is mandatory by spec — a registration is rejected without it.
    The computed `config_id` (`slack-{workspace}-{agent_name}`) must also be ≥10 chars to
    satisfy `DeploymentConfig.config_id`.
    """

    org_id: str
    agent_name: str
    workspace: str  # slack workspace id/slug — used in config_id
    base_url: str  # the agent's OpenAI-compatible endpoint
    model: str  # bare model name the endpoint serves
    system_prompt: str  # the agent's EFFECTIVE prompt, CUSTOMER-SUPPLIED (see module docstring)
    declared_tools: tuple[str, ...] = ()
    forbidden_topics: tuple[str, ...] = ()
    sandbox_channel_id: str = ""  # MANDATORY — sandbox binding; reject without it
    security_channel_id: str = ""  # where diffs post; separate id, also required
    rule_pack_ref: str | None = None  # area-04 rule-pack handle; optional until 04's packs land
    system_prompt_sensitive: bool = False  # if True, persist the prompt via SecretStore, not inline
    api_key: str | None = None  # the target endpoint's bearer key (optional — open/self-gatewayed endpoints need none); secret → persisted via SecretStore

    def __post_init__(self) -> None:
        required = {
            "org_id": self.org_id,
            "agent_name": self.agent_name,
            "workspace": self.workspace,
            "base_url": self.base_url,
            "model": self.model,
            "sandbox_channel_id": self.sandbox_channel_id,
            "security_channel_id": self.security_channel_id,
        }
        missing = [name for name, value in required.items() if not (value and str(value).strip())]
        if missing:
            raise ValueError(
                "SlackAgentTarget missing/blank required field(s): " + ", ".join(missing)
            )
        # config_id must satisfy DeploymentConfig (min_length=10). It is
        # f"slack-{workspace}-{agent_name}" → 7 fixed chars + workspace + agent_name.
        cid = config_id_for(self)
        if len(cid) < 10:
            raise ValueError(
                f"computed config_id {cid!r} is too short (<10 chars): lengthen "
                f"`workspace` and/or `agent_name`"
            )

    @classmethod
    def create(
        cls,
        *,
        org_id: str,
        agent_name: str,
        workspace: str,
        base_url: str,
        model: str,
        system_prompt: str,
        declared_tools: list[str] | tuple[str, ...] | None = None,
        forbidden_topics: list[str] | tuple[str, ...] | None = None,
        sandbox_channel_id: str = "",
        security_channel_id: str = "",
        rule_pack_ref: str | None = None,
        system_prompt_sensitive: bool = False,
        api_key: str | None = None,
    ) -> "SlackAgentTarget":
        """Factory accepting plain `list[str]` for the collection fields, normalized to tuples
        so callers don't have to pass tuples to keep the dataclass frozen/hashable."""
        return cls(
            org_id=org_id,
            agent_name=agent_name,
            workspace=workspace,
            base_url=base_url,
            model=model,
            system_prompt=system_prompt,
            declared_tools=tuple(declared_tools or ()),
            forbidden_topics=tuple(forbidden_topics or ()),
            sandbox_channel_id=sandbox_channel_id,
            security_channel_id=security_channel_id,
            rule_pack_ref=rule_pack_ref,
            system_prompt_sensitive=system_prompt_sensitive,
            api_key=api_key,
        )


@dataclass(frozen=True)
class RegisteredSlackAgent:
    """Result of `register_slack_agent`: the persisted agent id, the built (frozen)
    `DeploymentConfig`, and the originating target — so callers/tests can assert everything
    (config.base_url set, channels bound on the target, agent_id resolvable from the store)."""

    agent_id: str
    config: DeploymentConfig
    target: SlackAgentTarget


def config_id_for(target: SlackAgentTarget) -> str:
    """Stable config id for a Slack agent: `slack-{workspace}-{agent_name}`."""
    return f"slack-{target.workspace}-{target.agent_name}"


def slack_agent_to_config(target: SlackAgentTarget) -> DeploymentConfig:
    """Build the frozen `DeploymentConfig` for a registered Slack agent.

    Field validation only — there is no Slack introspection here; the effective system prompt
    is customer-supplied at registration (see module docstring). Setting `base_url` is what
    makes the reproduction panel resolve the provider to "custom" and route the config through
    `CustomHTTPAdapter` against the agent's endpoint.
    """
    return DeploymentConfig(
        config_id=config_id_for(target),
        customer_id=target.org_id,
        name=f"Slack · {target.agent_name}"[:100],
        target_model=target.model,
        system_prompt=target.system_prompt,
        declared_tools=list(target.declared_tools),
        forbidden_topics=list(target.forbidden_topics),
        base_url=target.base_url,  # base_url set ⇒ provider resolves to "custom" in target_panel
    )


def register_slack_agent(
    target: SlackAgentTarget,
    *,
    agent_store: "_SlackAgentStore | _AgentStoreLike",
    integration_store: "_IntegrationStoreLike | None" = None,
    slack_bot_token: str | None = None,
    slack_signing_secret: str | None = None,
) -> RegisteredSlackAgent:
    """Register a consented Slack agent as a ROGUE `DeploymentConfig`.

    Steps:
      1. Validate the target (the dataclass already fail-closes; we re-validate cheaply by
         re-running its invariant so a hand-mutated frozen instance still can't slip through).
      2. Build the frozen `DeploymentConfig` via `slack_agent_to_config` (carries `base_url`).
      3. Persist the agent-target row via `agent_store.put(target)` → `agent_id`.
      4. OPTIONAL Slack-app credential: if an `integration_store` and a `slack_bot_token` are
         provided, store the *Slack-app* credential by REUSING the existing `integrations`
         table via its store. This is a separate, injected path — we do NOT overload the
         `slack_registered_agents` row with the app credential. The bot token is stored as the
         encrypted secret; whether a signing secret was supplied is recorded (non-secret) in
         `config`.

    `agent_store` is injected (duck-typed) to avoid an import cycle with `agent_store.py`.
    """
    target.__post_init__()  # cheap re-validation; raises ValueError on any missing field

    config = slack_agent_to_config(target)
    agent_id = agent_store.put(target)

    if integration_store is not None and (slack_bot_token or slack_signing_secret):
        integration_store.put(
            org_id=target.org_id,
            kind="slack",
            name=f"slack-app-{target.workspace}",
            config={"signing_secret_present": bool(slack_signing_secret)},
            secret=slack_bot_token,
        )

    return RegisteredSlackAgent(agent_id=agent_id, config=config, target=target)


__all__ = [
    "SlackAgentTarget",
    "RegisteredSlackAgent",
    "config_id_for",
    "slack_agent_to_config",
    "register_slack_agent",
]
