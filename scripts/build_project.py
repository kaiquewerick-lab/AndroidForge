#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def run(cmd, cwd, log_file, env=None):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n=== Executando: {' '.join(cmd)}", flush=True)

    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)

        return process.wait(), str(log_file)


def load_json(value):
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def find_html(root):
    candidates = [
        root / "index.html",
        root / "public" / "index.html",
        root / "dist" / "index.html",
        root / "build" / "index.html",
        root / "www" / "index.html",
        root / "SaturnDesktopBETA.html",
    ]

    for path in candidates:
        if path.is_file():
            return path

    files = sorted(root.glob("*.html"))
    if files:
        return files[0]

    raise FileNotFoundError("Nenhum arquivo HTML encontrado no projeto.")


def prepare_web_project(root):
    entry = find_html(root)
    main = root / "app" / "src" / "main"
    assets = main / "assets" / "www"

    if assets.exists():
        shutil.rmtree(assets)

    assets.mkdir(parents=True)

    # Copia os arquivos do site preservando pastas e caminhos relativos.
    source = entry.parent

    for item in source.iterdir():
        if item.name in {
            "app", ".git", ".gradle", "build",
            "node_modules", ".androidforge",
        }:
            continue

        destination = assets / item.name

        if item.is_dir():
            shutil.copytree(
                item,
                destination,
                ignore=shutil.ignore_patterns(
                    "node_modules", ".git", "build"
                ),
            )
        elif item.is_file():
            shutil.copy2(item, destination)

    if not (assets / "index.html").exists():
        shutil.copy2(entry, assets / "index.html")

    (root / "settings.gradle").write_text(
        """
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = 'AndroidForgeWebApp'
include ':app'
""".strip() + "\n",
        encoding="utf-8",
    )

    (root / "build.gradle").write_text(
        "plugins { id 'com.android.application' version '8.1.4' apply false }\n",
        encoding="utf-8",
    )

    (root / "gradle.properties").write_text(
        "org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\n"
        "android.useAndroidX=true\n",
        encoding="utf-8",
    )

    app = root / "app"
    app.mkdir(exist_ok=True)

    (app / "build.gradle").write_text(
        """
plugins {
    id 'com.android.application'
}

android {
    namespace 'com.androidforge.webapp'
    compileSdk 34

    defaultConfig {
        applicationId 'com.androidforge.webapp'
        minSdk 23
        targetSdk 28
        versionCode 1
        versionName '1.0'
    }
}
""".strip() + "\n",
        encoding="utf-8",
    )

    java_dir = (
        main / "java" / "com" / "androidforge" / "webapp"
    )
    java_dir.mkdir(parents=True, exist_ok=True)

    (main / "AndroidManifest.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET"/>
    <application
        android:theme="@android:style/Theme.Material.Light.NoActionBar"
        android:label="AndroidForge App"
        android:usesCleartextTraffic="true">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
""",
        encoding="utf-8",
    )

    (java_dir / "MainActivity.java").write_text(
        """package com.androidforge.webapp;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.view.View;
import android.view.ViewGroup;

public class MainActivity extends Activity {
    private WebView webView;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());

        setContentView(webView);
        webView.loadUrl("file:///android_asset/www/index.html");
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
""",
        encoding="utf-8",
    )

    print(f"Projeto web preparado usando: {entry}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--detect", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument(
        "--variant",
        default="auto",
        choices=["auto", "debug", "release", "bundle"],
    )
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    detect = load_json(args.detect)
    toolchain = load_json(args.toolchain)

    root = Path(args.root).resolve()
    log_dir = (
        Path(args.log_dir)
        if args.log_dir
        else root.parent / "androidforge-logs"
    )
    log_dir.mkdir(parents=True, exist_ok=True)

    project_type = str(
        detect.get("project_type", "unknown")
    ).lower()

    use_wrapper = toolchain.get("use_wrapper", False)
    prep_commands = toolchain.get("prep_commands", []) or []

    if project_type in {"web", "html", "static-web", "website"}:
        try:
            prepare_web_project(root)
        except Exception as error:
            print(f"ERRO preparando projeto web: {error}", file=sys.stderr)
            return 1

        use_wrapper = False
        commands = [
            ["gradle", "assembleDebug"],
            ["gradle", "assembleRelease"],
        ]

        if args.variant == "debug":
            commands = commands[:1]
        elif args.variant == "release":
            commands = commands[1:]
        elif args.variant == "bundle":
            commands = [["gradle", "bundleRelease"]]

    else:
        commands = toolchain.get("build_commands", []) or []

        if args.variant != "auto":
            filtered = [
                cmd for cmd in commands
                if args.variant in " ".join(cmd).lower()
            ]
            if filtered:
                commands = filtered

    if not commands:
        print("ERRO: nenhum comando de compilação configurado.")
        return 1

    for cmd in prep_commands:
        code, _ = run(
            cmd, root,
            log_dir / f"prep-{int(time.time())}.log",
        )
        if code:
            print(f"Aviso: preparação falhou: {' '.join(cmd)}")

    success = False
    last_code = 1
    last_log = ""
    successful_command = None

    for command in commands:
        cmd = list(command)

        if use_wrapper and cmd and cmd[0].endswith("gradlew"):
            wrapper = Path(cmd[0])
            if wrapper.exists():
                wrapper.chmod(wrapper.stat().st_mode | 0o111)
                cmd = ["/bin/sh", str(wrapper)] + cmd[1:]

        last_code, last_log = run(
            cmd,
            root,
            log_dir / f"build-{int(time.time())}.log",
        )

        if last_code == 0:
            success = True
            successful_command = cmd
            break

    result = {
        "project_root": str(root),
        "project_type": project_type,
        "build_succeeded": success,
        "successful_command": successful_command,
        "exit_code": last_code,
        "log_file": last_log,
        "prep_commands_run": prep_commands,
        "build_commands_attempted": commands,
    }

    rendered = json.dumps(result, indent=2)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as file:
            file.write(f"build_succeeded={'true' if success else 'false'}\n")
            file.write(f"exit_code={last_code}\n")
            file.write(f"log_file={last_log}\n")
            if successful_command:
                file.write(
                    f"successful_command={' '.join(successful_command)}\n"
                )
            file.write(f"json<<EOF\n{rendered}\nEOF\n")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
