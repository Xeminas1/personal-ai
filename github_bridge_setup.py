"""One-time interactive setup for the private XemAi <-> ChatGPT bridge."""
from __future__ import annotations

import getpass
from app.config import DATA_DIR
from app.github_bridge import BridgeError, setup


def main() -> int:
    print("XemAi Private GitHub Bridge")
    print("--------------------------")
    print("Create a separate PRIVATE GitHub repo with Issues enabled.")
    print("Create a fine-grained GitHub personal access token restricted")
    print("to that repo: Repository permissions -> Issues: Read and write.")
    print("Metadata read permission is implicit. No Contents permission is needed.")
    print("Do NOT paste your token into ChatGPT or XemAi chat.")
    print()
    repo = input("Private repo (owner/name): ").strip()
    token = getpass.getpass("GitHub fine-grained token (hidden): ").strip()
    try:
        setup(DATA_DIR, repo, token)
    except BridgeError as error:
        print("Setup unsuccessful: " + str(error))
        return 1
    print()
    print("Bridge configured successfully for: " + repo)
    print("Only your explicit 'bridge approve CODE' commands can send messages.")
    print("Try 'bridge status' in XemAi chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
