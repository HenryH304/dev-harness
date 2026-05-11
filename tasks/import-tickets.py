#!/usr/bin/env python3
"""Import tickets from a prd.json file into dev-harness via the API.

Usage:
    python3 tasks/import-tickets.py tasks/in-merge-state-tickets.json <project> [base_url]

Example:
    python3 tasks/import-tickets.py tasks/in-merge-state-tickets.json dev-harness http://localhost:9080
"""

import json
import sys
import urllib.request
import urllib.error

def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: import-tickets.py <json-file> <project> [base_url]")
        sys.exit(1)

    json_file = sys.argv[1]
    project = sys.argv[2]
    base_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:9080"

    with open(json_file) as f:
        data = json.load(f)

    stories = data.get("userStories", [])
    story_id_to_ticket_id: dict[str, int] = {}

    for story in stories:
        payload = json.dumps({
            "project": project,
            "title": story["title"],
            "description": story["description"],
            "acceptance_criteria": story.get("acceptanceCriteria", []),
            "priority": story.get("priority", 3),
        }).encode()

        req = urllib.request.Request(
            f"{base_url}/api/tickets",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                ticket = json.loads(resp.read())
                ticket_id = ticket["id"]
                story_id_to_ticket_id[story["id"]] = ticket_id
                print(f"  Created ticket #{ticket_id}: {story['title'][:60]}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  ERROR creating '{story['title'][:40]}': {e.code} {body}")
            sys.exit(1)

    # Wire dependencies
    for story in stories:
        ticket_id = story_id_to_ticket_id.get(story["id"])
        if not ticket_id:
            continue
        for dep_story_id in story.get("dependencies", []):
            dep_ticket_id = story_id_to_ticket_id.get(dep_story_id)
            if not dep_ticket_id:
                continue
            payload = json.dumps({"depends_on_ticket_id": dep_ticket_id}).encode()
            req = urllib.request.Request(
                f"{base_url}/api/tickets/{ticket_id}/dependencies",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req):
                    print(f"  Dependency: #{ticket_id} depends on #{dep_ticket_id}")
            except urllib.error.HTTPError as e:
                print(f"  WARN: dependency #{ticket_id}→#{dep_ticket_id}: {e.code}")

    print(f"\nDone — {len(story_id_to_ticket_id)} tickets created in project '{project}'")

if __name__ == "__main__":
    main()
