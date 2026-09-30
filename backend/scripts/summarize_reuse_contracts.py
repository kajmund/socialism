"""Render the dedicated reuse job's JUnit outcomes, including unfinished contracts."""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


def summary(path: str) -> str:
    groups = defaultdict(lambda: {"passed": 0, "pending": 0, "failed": 0, "seconds": 0.0})
    reasons = set()
    for test in ET.parse(path).iter("testcase"):
        module = test.attrib["classname"].rsplit(".", 1)[-1]
        group = module.removeprefix("test_")
        row = groups[group]
        row["seconds"] += float(test.attrib.get("time", "0"))
        skipped = test.find("skipped")
        if skipped is not None:
            row["pending"] += 1
            reasons.add(skipped.attrib.get("message", ""))
        elif test.find("failure") is not None or test.find("error") is not None:
            row["failed"] += 1
        else:
            row["passed"] += 1
    lines = [
        "## Research reuse contracts",
        "",
        "External services are mocked; network access is blocked.",
        "",
        "| Step | Passed | Pending product contracts | Failed | CI seconds |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for group, row in sorted(groups.items()):
        lines.append(
            f"| {group} | {row['passed']} | {row['pending']} | {row['failed']} | {row['seconds']:.3f} |"
        )
    if reasons:
        lines.extend(["", "Pending contracts use strict XFAIL. Unexpected success fails CI.", ""])
        lines.extend(f"- {reason}" for reason in sorted(reasons))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary(sys.argv[1]))
