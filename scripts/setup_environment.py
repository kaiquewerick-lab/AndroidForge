#!/usr/bin/env python3
"""AndroidForge — Toolchain Setup."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML not installed. Run: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = REPO_ROOT / "config" / "toolchain-rules.yaml"


def load_rules(path: Path | None = None) -> dict[str, Any]:
    p = path or RULES_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data or {}


def major(v: str) -> int:
    try:
        return int(str(v).split(".")[0])
    except (ValueError, IndexError):
        return 0


def minor(v: str) -> int:
    try:
        return int(str(v).split(".")[1])
    except (ValueError, IndexError):
        return 0


def pick_jdk_for_agp(
    agp: str | None, rules: dict
) -> str:
    if not agp:
        return "17"

    version = major(agp)

    if version >= 8:
        return "17"
    if version == 7:
        return "11"
    if version == 4:
        return "11"
    if version <= 3:
        return "8"

    for pattern, jdk in rules.get("agp_to_jdk", {}).items():
        if pattern.endswith(".x"):
            if str(agp).startswith(pattern[:-2]):
                return str(jdk)
        elif str(agp).startswith(pattern):
            return str(jdk)

    return "17"


def pick_jdk_for_gradle(
    gradle: str | None, rules: dict
) -> str:
    if not gradle:
        return "17"

    version = major(gradle)

    if version >= 8:
        return "17"
    if version == 7:
        return "11"
    if version <= 6:
        return "8"

    return "17"


def pick_gradle_for_agp(
    agp: str | None, rules: dict
) -> str | None:
    if not agp:
        return None

    mapping = rules.get("agp_to_gradle", {})

    if agp in mapping:
        return str(mapping[agp])

    parts = str(agp).split(".")

    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in mapping:
            return str(mapping[prefix])

    version = major(agp)

    for key, value in mapping.items():
        if major(key) == version:
            return str(value)

    return None


def pick_flutter_version(
    detect: dict, rules: dict
) -> str:
    flutter = detect.get("flutter", {}) or {}
    constraint = flutter.get("flutter_version_constraint")

    if constraint:
        match = re.search(r"(\d+\.\d+\.\d+)", constraint)
        if match:
            return match.group(1)

    return str(
        rules.get("flutter", {}).get(
            "default_version", "3.24.0"
        )
    )


def pick_ndk_version(
    detect: dict, rules: dict
) -> str:
    ndk_version = (
        detect.get("versions", {}) or {}
    ).get("ndk_version")

    if ndk_version:
        return str(ndk_version)

    return str(
        rules.get("ndk", {}).get(
            "default_version", "26.1.10909125"
        )
    )


def determine_legacy_fixes(
    detect: dict, rules: dict
) -> list[dict]:
    fixes: list[dict] = []
    wrapper = detect.get("wrapper", {}) or {}
    gradle_version = wrapper.get("version")

    has_local = (
        "local.properties"
        in detect.get("indicator_files", {})
    )

    if wrapper.get("missing_jar") or not wrapper.get("present"):
        fixes.append({
            "name": "patch_gradle_wrapper",
            "reason": "Missing or corrupt gradle-wrapper.jar",
        })

    if wrapper.get("uses_http"):
        fixes.append({
            "name": "migrate_https",
            "reason": "Wrapper uses http:// distribution URL",
        })

    if gradle_version and major(gradle_version) < 4:
        fixes.append({
            "name": "disable_gradle_daemon",
            "reason": f"Very old Gradle: {gradle_version}",
        })

    if (
        not has_local
        and detect.get("project_type") in ("gradle", "flutter")
    ):
        fixes.append({
            "name": "inject_local_properties",
            "reason": "local.properties missing",
        })

    return fixes


def apply_fixes(
    detect: dict,
    fixes: list[dict],
    android_sdk_root: str,
) -> list[str]:
    """Apply compatibility fixes to the build workspace."""
    applied: list[str] = []
    root = Path(detect["project_root"])
    props = root / "gradle" / "wrapper" / "gradle-wrapper.properties"

    for fix in fixes:
        name = fix["name"]

        if name == "migrate_https" and props.exists():
            content = props.read_text(
                encoding="utf-8", errors="replace"
            )
            updated = re.sub(
                r"distributionUrl=http://",
                "distributionUrl=https://",
                content,
            )

            if updated != content:
                props.write_text(updated, encoding="utf-8")
                applied.append(
                    f"Migrated wrapper URL to HTTPS in {props}"
                )

        elif name == "inject_local_properties":
            (root / "local.properties").write_text(
                f"sdk.dir={android_sdk_root}\n",
                encoding="utf-8",
            )
            applied.append("Created local.properties")

        elif name == "disable_gradle_daemon":
            gradle_props = root / "gradle.properties"
            content = (
                gradle_props.read_text(encoding="utf-8")
                if gradle_props.exists()
                else ""
            )

            if "org.gradle.daemon" not in content:
                with gradle_props.open(
                    "a", encoding="utf-8"
                ) as file:
                    file.write(
                        "\n# AndroidForge: old Gradle compatibility\n"
                        "org.gradle.daemon=false\n"
                    )
                applied.append(
                    "Disabled Gradle daemon for old Gradle"
                )

        elif name == "patch_gradle_wrapper":
            applied.append(
                "Flagged wrapper for regeneration"
            )

    heap_line = (
        "org.gradle.jvmargs=-Xmx4g "
        "-XX:+UseG1GC -Dfile.encoding=UTF-8"
    )

    androidx_lines = [
        "android.useAndroidX=true",
        "android.enableJetifier=true",
    ]

    def inject_gradle_properties(
        props_path: Path,
        location_label: str,
    ) -> None:
        if props_path.exists():
            content = props_path.read_text(
                encoding="utf-8", errors="replace"
            )
            changes: list[str] = []

            match = re.search(
                r"^org\.gradle\.jvmargs\s*=\s*(.+)$",
                content,
                re.MULTILINE,
            )

            if match:
                existing = match.group(1).strip()
                heap_match = re.search(
                    r"-Xmx(\d+)([gm])",
                    existing,
                    re.IGNORECASE,
                )

                if heap_match:
                    size = int(heap_match.group(1))
                    unit = heap_match.group(2).lower()
                    existing_mb = size * (
                        1024 if unit == "g" else 1
                    )

                    if existing_mb < 4096:
                        updated = re.sub(
                            r"^org\.gradle\.jvmargs\s*=.*$",
                            heap_line,
                            content,
                            flags=re.MULTILINE,
                        )

                        if updated != content:
                            content = updated
                            changes.append("increased JVM heap")
            else:
                content += (
                    "\n# AndroidForge: JVM heap\n"
                    f"{heap_line}\n"
                )
                changes.append("added JVM heap")

            if not re.search(
                r"^android\.useAndroidX\s*=",
                content,
                re.MULTILINE,
            ):
                content += (
                    "\n# AndroidForge: AndroidX compatibility\n"
                )
                for line in androidx_lines:
                    content += f"{line}\n"
                changes.append("enabled AndroidX")

            if changes:
                props_path.write_text(
                    content, encoding="utf-8"
                )
                applied.append(
                    f"Updated {location_label}: "
                    + ", ".join(changes)
                )

        else:
            props_path.parent.mkdir(
                parents=True, exist_ok=True
            )
            content = (
                "# AndroidForge: JVM heap\n"
                f"{heap_line}\n"
                "org.gradle.daemon=false\n"
                "\n# AndroidForge: AndroidX compatibility\n"
            )

            for line in androidx_lines:
                content += f"{line}\n"

            props_path.write_text(
                content, encoding="utf-8"
            )
            applied.append(
                f"Created {location_label} with JVM and AndroidX settings"
            )

    inject_gradle_properties(
        root / "gradle.properties",
        "gradle.properties (root)",
    )

    android_dir = root / "android"

    if android_dir.is_dir():
        inject_gradle_properties(
            android_dir / "gradle.properties",
            "android/gradle.properties",
        )

    home_gradle = Path.home() / ".gradle" / "gradle.properties"

    inject_gradle_properties(
        home_gradle,
        "~/.gradle/gradle.properties",
    )

    inject_repositories(
        root,
        applied,
        is_flutter=bool(
            (detect.get("flutter") or {}).get("is_flutter")
        ),
    )

    return applied


def inject_repositories(
    root: Path,
    applied: list[str],
    is_flutter: bool,
) -> None:
    """Preserve repository configuration from the source project.

    Repository declarations are intentionally not injected here.
    The source project's settings.gradle files remain authoritative.
    """
    return


def main() -> int:
    """AndroidForge toolchain setup."""
    parser = argparse.ArgumentParser(
        description="AndroidForge toolchain setup"
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Project root path",
    )
    parser.add_argument(
        "--detect",
        required=True,
        help="Detection JSON (string or file path)",
    )
    parser.add_argument(
        "--rules",
        default=None,
        help="Path to toolchain-rules.yaml",
    )
    parser.add_argument(
        "--android-sdk",
        default=os.environ.get(
            "ANDROID_SDK_ROOT",
            "/usr/local/lib/android/sdk",
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON summary to this file",
    )

    args = parser.parse_args()
    rules = load_rules(
        Path(args.rules) if args.rules else None
    )

    detect_path = Path(args.detect)

    if detect_path.exists():
        detect = json.loads(
            detect_path.read_text(encoding="utf-8")
        )
    else:
        detect = json.loads(args.detect)

    # Keep the supplied root consistent with the detected project.
    if not detect.get("project_root"):
        detect["project_root"] = args.root

    versions = detect.get("versions", {}) or {}
    wrapper = detect.get("wrapper", {}) or {}

    agp = versions.get("agp_version")
    gradle_wrapper_version = wrapper.get("version")
    java_version = versions.get("java_version")
    kotlin_version = versions.get("kotlin_version")

    jdk_candidates = [
        pick_jdk_for_agp(agp, rules),
        pick_jdk_for_gradle(gradle_wrapper_version, rules),
    ]

    if java_version:
        jdk_candidates.append(str(java_version))

    chosen_jdk = max(
        jdk_candidates,
        key=lambda version: (
            major(version), minor(version)
        ),
    )

    chosen_gradle = gradle_wrapper_version

    if not chosen_gradle:
        chosen_gradle = pick_gradle_for_agp(agp, rules)

    if not chosen_gradle:
        chosen_gradle = "8.0"

    use_wrapper = bool(wrapper.get("present"))

    if wrapper.get("uses_http"):
        use_wrapper = True

    needs_flutter = bool(
        (detect.get("flutter") or {}).get("is_flutter")
    )

    chosen_flutter = (
        pick_flutter_version(detect, rules)
        if needs_flutter
        else None
    )

    needs_ndk = bool(
        (detect.get("native") or {}).get("has_native")
    )

    chosen_ndk = (
        pick_ndk_version(detect, rules)
        if needs_ndk
        else None
    )

    fixes = determine_legacy_fixes(detect, rules)

    applied_fixes = apply_fixes(
        detect,
        fixes,
        args.android_sdk,
    )

    prep_commands: list[list[str]] = []

    if needs_flutter:
        prep_commands = [["flutter", "pub", "get"]]
        build_commands = [
            ["flutter", "build", "apk", "--debug"],
            ["flutter", "build", "apk", "--release"],
        ]
    else:
        gradlew = Path(detect["project_root"]) / "gradlew"
        gradle_command = (
            str(gradlew)
            if use_wrapper and gradlew.exists()
            else "gradle"
        )

        build_commands = [
            [gradle_command, "assembleDebug"],
            [gradle_command, "assembleRelease"],
            [gradle_command, "bundleDebug"],
        ]

    result = {
        "project_root": detect["project_root"],
        "jdk_version": chosen_jdk,
        "gradle_version": chosen_gradle,
        "agp_version": agp,
        "kotlin_version": kotlin_version,
        "ndk_version": chosen_ndk,
        "flutter_version": chosen_flutter,
        "use_gradle_wrapper": use_wrapper,
        "needs_flutter": needs_flutter,
        "needs_ndk": needs_ndk,
        "needs_gradle": detect.get("project_type")
        in ("gradle", "flutter"),
        "legacy_fixes_applied": applied_fixes,
        "prep_commands": prep_commands,
        "build_commands": build_commands,
    }

    output = json.dumps(result, indent=2)

    if args.output:
        Path(args.output).write_text(
            output, encoding="utf-8"
        )
    else:
        print(output)

    github_output = os.environ.get("GITHUB_OUTPUT")

    if github_output:
        with open(
            github_output, "a", encoding="utf-8"
        ) as file:
            file.write(f"jdk_version={chosen_jdk}\n")
            file.write(f"gradle_version={chosen_gradle}\n")

            if agp:
                file.write(f"agp_version={agp}\n")

            if kotlin_version:
                file.write(
                    f"kotlin_version={kotlin_version}\n"
                )

            if chosen_ndk:
                file.write(f"ndk_version={chosen_ndk}\n")

            file.write(
                "needs_flutter="
                f"{'true' if needs_flutter else 'false'}\n"
            )
            file.write(
                "needs_ndk="
                f"{'true' if needs_ndk else 'false'}\n"
            )
            file.write(
                "needs_gradle="
                f"{'true' if result['needs_gradle'] else 'false'}\n"
            )
            file.write(
                f"use_wrapper={'true' if use_wrapper else 'false'}\n"
            )

            if chosen_flutter:
                file.write(
                    f"flutter_version={chosen_flutter}\n"
                )

            file.write(
                f"json<<EOF\n{json.dumps(result)}\nEOF\n"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
