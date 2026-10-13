"""
Merkle root and proofs.

A Merkle root is one hash that stands for a whole batch of records.
It lets a student prove their own mark is in the official batch
without revealing anyone else's mark.
"""

import hashlib
import json

from ledger import connect, add_entry
from compute import read_scores, load_items


def leaf_hash(roll, item_id, value):
    """One leaf per mark. Fixed text format so the hash is repeatable."""
    material = json.dumps(
        {"roll": roll, "item_id": item_id, "value": value},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def pair_hash(left, right):
    """Two child hashes joined and hashed again."""
    return hashlib.sha256((left + right).encode()).hexdigest()


def build_leaves(course_id):
    """Every current mark in the course, sorted so the order never varies."""
    scores = read_scores(course_id)
    items = load_items(course_id)
    item_ids = sorted(item_id for item_id, _, _ in items)

    leaves = []
    for roll in sorted(scores):
        for item_id in item_ids:
            if item_id in scores[roll]:
                leaves.append(
                    {
                        "roll": roll,
                        "item_id": item_id,
                        "value": scores[roll][item_id],
                        "hash": leaf_hash(roll, item_id, scores[roll][item_id]),
                    }
                )
    return leaves


def build_tree(leaf_hashes):
    """Returns every level, bottom first, root last.
    An odd node at any level is paired with itself."""
    if not leaf_hashes:
        return [[hashlib.sha256(b"").hexdigest()]]

    levels = [leaf_hashes]
    while len(levels[-1]) > 1:
        current = levels[-1]
        nxt = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]
            nxt.append(pair_hash(left, right))
        levels.append(nxt)
    return levels


def merkle_root(course_id):
    leaves = build_leaves(course_id)
    levels = build_tree([leaf["hash"] for leaf in leaves])
    return levels[-1][0], len(leaves)


def build_proof(course_id, roll, item_id):
    """The few hashes a verifier needs, instead of the whole batch."""
    leaves = build_leaves(course_id)
    hashes = [leaf["hash"] for leaf in leaves]

    index = None
    for position, leaf in enumerate(leaves):
        if leaf["roll"] == roll and leaf["item_id"] == item_id:
            index = position
            value = leaf["value"]
            break

    if index is None:
        return None

    levels = build_tree(hashes)
    path = []
    for level in levels[:-1]:
        if index % 2 == 0:
            sibling = level[index + 1] if index + 1 < len(level) else level[index]
            side = "right"
        else:
            sibling = level[index - 1]
            side = "left"
        path.append({"hash": sibling, "side": side})
        index = index // 2

    return {"roll": roll, "item_id": item_id, "value": value, "path": path}


def verify_proof(proof, expected_root):
    """Rebuild the root from one leaf and its path."""
    current = leaf_hash(proof["roll"], proof["item_id"], proof["value"])
    for step in proof["path"]:
        if step["side"] == "right":
            current = pair_hash(current, step["hash"])
        else:
            current = pair_hash(step["hash"], current)
    return current == expected_root


def publish_root(course_id, actor):
    """Locks the batch. The root itself becomes a block on the chain."""
    root, count = merkle_root(course_id)
    add_entry(
        "merkle_root",
        {"course_id": course_id, "root": root, "leaf_count": count},
        actor,
    )
    return root, count


if __name__ == "__main__":
    COURSE = "EEE311-2025-2"

    root, count = merkle_root(COURSE)
    print(f"Marks in this batch : {count}")
    print(f"Merkle root         : {root}")

    proof = build_proof(COURSE, "23702051", "EEE311-CT1")
    print()
    print("Proof for roll 23702051, CT1")
    print(f"  mark            : {proof['value']}")
    print(f"  hashes needed   : {len(proof['path'])} (instead of all {count})")
    print(f"  proof valid     : {verify_proof(proof, root)}")

    tampered = dict(proof)
    tampered["value"] = 95
    print()
    print("Same proof, but claiming the mark was 95")
    print(f"  proof valid     : {verify_proof(tampered, root)}")
