"""ROGUE SDK provider registration — offline against MockTransport.

Run from the sdk/ directory (no API key, no network required):

    PYTHONPATH=src python3 examples/providers.py

Before ROGUE can scan a deployment it needs credentials to reach the model
provider. Register them with the typed helpers below. Secrets are write-only:
the response carries only non-secret metadata (id / provider / label), never
the key you sent.
"""

from rogue import Rogue, MockTransport


def main() -> None:
    rogue = Rogue(api_key="demo", transport=MockTransport())

    rogue.register(
        name="Customer Support Agent",
        model="gpt-5",
        system_prompt="You are a helpful support agent.",
    )

    print("Registering provider credentials (secrets are never echoed back):")
    print(" ", rogue.register_openai(api_key="sk-fake-openai", label="prod"))
    print(" ", rogue.register_anthropic(api_key="sk-ant-fake"))
    print(" ", rogue.register_vertex(project="my-gcp-project", location="us-central1"))
    print(" ", rogue.register_custom(base_url="https://llm.internal.example.com/v1"))

    print()
    print("All registered providers:")
    for p in rogue.providers():
        print(f"  {p['id']}  provider={p['provider']:<10} label={p['label']}")


if __name__ == "__main__":
    main()
