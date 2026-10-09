"""Optional source navigation derived only from public packet records."""
from copy import deepcopy


def build_source_navigation(packet):
    """Locate every delivered anchor without changing or interpreting its evidence."""
    records = packet.get("records", [])
    sources = {(row["ref"]["id"], row["ref"]["version"]): row["body"]
               for row in records if row["ref"]["collection"] == "sources"}
    anchors = []
    for row in records:
        if row["ref"]["collection"] != "anchors":
            continue
        body = row["body"]
        source = sources.get((body["source_id"], body["source_version"]), {})
        anchors.append({
            "anchor_id": row["ref"]["id"], "anchor_version": row["ref"]["version"],
            "source_id": body["source_id"], "source_version": body["source_version"],
            "source_path": source.get("path"), "source_sha256": source.get("blob_sha256"),
            "locator": deepcopy(body["locator"]),
            "source_limitation": source.get("limitation"), "anchor_limitation": body.get("limitation"),
        })
    anchors.sort(key=lambda row: (row["source_id"], row["source_version"], row["anchor_id"], row["anchor_version"]))
    return {"packet_id": packet["packet_id"],
            "note": "Optional navigation of public packet sources. Locations do not establish readability, "
                    "inspection or mathematical support.",
            "anchors": anchors}
