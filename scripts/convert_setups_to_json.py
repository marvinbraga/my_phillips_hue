"""
Script to convert all legacy setup classes to JSON format.

This script reads all setup classes from marvin_hue.setups and converts them
to JSON format, merging with existing setups in .res/setups.json.
"""

import json
import os
import sys

# Add parent directory to path to import marvin_hue
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from marvin_hue.factories import LightConfigEnum


def convert_all_setups():
    """Convert all setup classes to JSON format."""

    # Get existing JSON data
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".res",
        "setups.json",
    )

    # Load existing setups
    existing_setups = {}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for setup in data.get("setups", []):
                existing_setups[setup["name"]] = setup

    # Convert all enum setups
    all_setups = []
    converted_names = []

    for enum_member in LightConfigEnum:
        try:
            instance = enum_member.get_instance()
            setup_dict = instance.to_dict()

            # Use description from enum if not in class
            if not setup_dict.get("description"):
                setup_dict["description"] = enum_member.description

            # Don't override existing setups from JSON
            if setup_dict["name"] not in existing_setups:
                all_setups.append(setup_dict)
                converted_names.append(setup_dict["name"])
            else:
                print(f"Skipping '{setup_dict['name']}' - already exists in JSON")

        except Exception as e:
            print(f"Error converting {enum_member.name}: {e}")

    # Add existing setups that weren't converted
    for name, setup in existing_setups.items():
        all_setups.append(setup)

    # Sort by name for consistency
    all_setups.sort(key=lambda x: x["name"])

    # Write to JSON
    output_data = {"setups": all_setups}

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print("\nConversion complete!")
    print(f"Total setups: {len(all_setups)}")
    print(f"Newly converted: {len(converted_names)}")
    print(f"Already in JSON: {len(existing_setups)}")
    print(f"\nOutput written to: {json_path}")

    if converted_names:
        print("\nConverted setups:")
        for name in sorted(converted_names):
            print(f"  - {name}")


if __name__ == "__main__":
    convert_all_setups()
