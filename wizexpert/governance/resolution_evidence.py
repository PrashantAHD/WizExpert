"""Describe what actually changed when Wiz closed issues, and the risk that removed.

Inputs come from the fields shown on a resolved issue page (portal GraphQL
``issuesV2``/``issue``): ``status``, ``resolutionReason``, ``sourceRule.risks`` and
``resolutionEvidence.changes`` (resource *types* and short property values only;
resource names are never used).
"""

from __future__ import annotations

import re
from collections import Counter

RISKS = {
    "UNPROTECTED_PRINCIPAL": "unprotected identity",
    "INSECURE_USE_OF_SECRETS": "insecure secrets",
    "UNPROTECTED_DATA": "sensitive data exposure",
    "EXTERNAL_EXPOSURE": "external exposure",
    "RELIABILITY_IMPACT": "reliability",
    "INSECURE_KUBERNETES_CLUSTER": "insecure Kubernetes",
    "VULNERABILITY": "vulnerability",
    "HIGH_PRIVILEGES": "excessive privileges",
}
ACRONYMS = {
    "iam": "IAM",
    "vm": "VM",
    "vpc": "VPC",
    "sas": "SAS",
    "dns": "DNS",
    "kubernetes": "Kubernetes",
}

# (singular, plural) descriptions of what changed, keyed by resource type.
DELETED = {
    "IAM_BINDING": (
        "IAM role binding removed (access revoked)",
        "IAM role bindings removed (access revoked)",
    ),
    "SERVICE_ACCOUNT": ("service account removed", "service accounts removed"),
    "USER_ACCOUNT": ("user account removed", "user accounts removed"),
    "ACCESS_KEY": ("access key removed", "access keys removed"),
    "GROUP": ("privileged group removed", "privileged groups removed"),
    "LOCAL_USER": ("weak-password local user removed", "weak-password local users removed"),
    "SECRET_INSTANCE": ("exposed secret removed", "exposed secrets removed"),
    "VIRTUAL_MACHINE": ("VM deleted", "VMs deleted"),
    "VIRTUAL_NETWORK": ("VPC/VNet deleted", "VPCs/VNets deleted"),
    "SUBSCRIPTION": (
        "cloud account removed from Wiz scope",
        "cloud accounts removed from Wiz scope",
    ),
    "DATA_FINDING": ("sensitive data finding cleared", "sensitive data findings cleared"),
    "ENDPOINT": ("public endpoint removed", "public endpoints removed"),
    "AUTHENTICATION_CONFIGURATION": (
        "SSH password authentication removed",
        "SSH password authentication removed",
    ),
}
ADDED = {
    "CLOUD_LOG_CONFIGURATION": ("logging configuration enabled", "logging configurations enabled")
}
# Resources Wiz may list more than once in a single issue's evidence.
ONCE_PER_ISSUE = {"SUBSCRIPTION"}
MODIFIED = {
    ("hasHighPrivileges", False): (
        "high privileges removed from {n} {type}",
        "high privileges removed from {n} {types}",
    ),
    ("active", False): ("{n} {type} deactivated", "{n} {types} deactivated"),
    ("inactiveInLast90Days", False): (
        "{n} dormant {type} back in active use",
        "{n} dormant {types} back in active use",
    ),
    ("inactiveInLast90Days", None): (
        "{n} dormant {type} back in active use",
        "{n} dormant {types} back in active use",
    ),
}
# Wiz bookkeeping records that duplicate a more meaningful change in the same evidence.
REDUNDANT = {"SECRET_DATA", "HOSTED_TECHNOLOGY", "EXCESSIVE_ACCESS_FINDING"}


def words(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).replace("_", " ").lower().strip()
    return " ".join(ACRONYMS.get(w, w) for w in value.split())


def noun(resource_type: str, count: int) -> str:
    text = words(resource_type)
    if count == 1 or text.endswith(("data", "s")):
        return text
    return (
        text[:-1] + "ies"
        if text.endswith("y") and not text.endswith(("ay", "ey", "oy"))
        else text + "s"
    )


def change_keys(changes: dict | None) -> Counter:
    """Counter of change keys for one issue: ``("deleted", TYPE)``, ``("added", TYPE)``,
    ``("modified", TYPE, property, new_value)`` or ``("unlinked", TYPE)``."""
    keys: Counter = Counter()
    changes = changes or {}
    for item in changes.get("deletedResources") or []:
        if item["type"] not in REDUNDANT:
            keys[("deleted", item["type"])] += 1
    for item in changes.get("addedResources") or []:
        keys[("added", item["type"])] += 1
    for item in changes.get("modifiedResources") or []:
        for prop in item.get("modifiedProperties") or []:
            value = prop.get("newValue")
            keys[
                (
                    "modified",
                    item["entity"]["type"],
                    prop["propertyKey"],
                    value if isinstance(value, (bool, type(None))) else str(value),
                )
            ] += 1
    if not keys:
        for item in changes.get("deletedRelationships") or []:
            keys[("unlinked", item["from"]["type"])] += 1
    for key in keys:
        if key[1] in ONCE_PER_ISSUE:
            keys[key] = 1
    return keys


def describe(key: tuple, count: int) -> str:
    kind, resource = key[0], key[1]
    if kind == "deleted":
        singular, many = DELETED.get(
            resource, (f"{noun(resource, 1)} removed", f"{noun(resource, 2)} removed")
        )
    elif kind == "added":
        singular, many = ADDED.get(
            resource, (f"{noun(resource, 1)} added", f"{noun(resource, 2)} added")
        )
    elif kind == "modified":
        template = MODIFIED.get((key[2], key[3]))
        if template is None:
            label = f"{{n}} {{type}} {words(key[2])} set to {key[3]}"
            template = (label, label.replace("{type}", "{types}"))
        return template[0 if count == 1 else 1].format(
            n=f"{count:,}", type=noun(resource, 1), types=noun(resource, 2)
        )
    else:
        singular, many = (
            f"{noun(resource, 1)} access removed",
            f"{noun(resource, 2)} access removed",
        )
    return f"{count:,} {singular if count == 1 else many}"


def summarize(issues: list[dict], verified_at: str, top: int = 3) -> dict:
    """Aggregate one rule group's closures into the snapshot ``resolution`` object."""
    reasons, changes, risks = Counter(), Counter(), []
    for issue in issues:
        reasons[issue.get("resolutionReason") or "UNSPECIFIED"] += 1
        for risk in issue.get("risks") or []:
            if risk not in risks:
                risks.append(risk)
        if issue.get("status") == "RESOLVED":
            changes.update(change_keys((issue.get("resolutionEvidence") or {}).get("changes")))
    return {
        "verified_at": verified_at,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "changes": [
            {"text": describe(key, count), "count": count}
            for key, count in changes.most_common(top)
        ],
        "risks": risks,
    }


def plain(text: str) -> str:
    """Change text without counts, as a sentence.

    ``18 VPCs/VNets deleted`` -> ``VPCs/VNets deleted``.
    """
    text = re.sub(r"\b\d[\d,]*\s+", "", text).strip()
    return text[:1].upper() + text[1:]


def changed_text(resolution: dict, resolved: int) -> str:
    """What actually changed, without counts (the issue column carries them), e.g.
    ``IAM role bindings removed (access revoked). Service accounts removed.``"""
    if not resolved:
        return "Risk reviewed and accepted by the team."
    if not resolution["changes"]:
        return "Change detail not recorded by Wiz."
    return " ".join(plain(change["text"]) + "." for change in resolution["changes"])


def risk_text(resolution: dict, resolved: int, accepted: int) -> str:
    """Risk outcome; accepted-risk counts are shown in the issue column, not repeated here."""
    risks = ", ".join(RISKS.get(r, words(r)) for r in resolution["risks"]) or "the rule's"
    if resolved:
        return f"Reduced {risks} risk."
    return "Accepted risk documented in Wiz." if accepted else ""
