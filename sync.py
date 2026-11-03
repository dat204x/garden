#!/usr/bin/env python3
"""
Sync published notes from Obsidian Vault to Quartz Digital Garden.
Usage:
    python3 sync.py              # Sync files
    python3 sync.py --build      # Sync files & build
    python3 sync.py --preview    # Sync files & serve locally at http://localhost:8080
    python3 sync.py --push       # Sync files, commit & push to GitHub Pages
    python3 sync.py --status     # List which notes are marked publish: true
"""

import os
import sys
import re
import shutil
import subprocess
import argparse
from pathlib import Path

VAULT_DIR = Path("/home/admin/documents/Vault").resolve()
QUARTZ_DIR = Path("/home/admin/projects/quartz").resolve()
CONTENT_DIR = QUARTZ_DIR / "content"

# Folders to ignore when scanning Vault
IGNORED_DIRS = {".git", ".obsidian", ".agents", ".trash", "Meta/Templates", ".system_generated"}

def parse_frontmatter(content: str) -> dict:
    """Extract simple key-value pairs from YAML frontmatter."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_text = parts[1]
    data = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().lower()
            if val in ("true", "yes", "1"):
                data[key] = True
            elif val in ("false", "no", "0"):
                data[key] = False
            else:
                data[key] = val
    return data

def is_published(file_path: Path) -> bool:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            header = f.read(2048)
            fm = parse_frontmatter(header)
            # Accept both publish: true and dg-publish: true
            return fm.get("publish") is True or fm.get("dg-publish") is True
    except Exception:
        return False

def find_attachments(md_content: str) -> set:
    """Find image/file attachments referenced in markdown text."""
    attachments = set()
    # Wiki links: ![[image.png]] or ![[image.png|300]]
    wiki_matches = re.findall(r'!\[\[(.*?)\]\]', md_content)
    for match in wiki_matches:
        filename = match.split("|")[0].strip()
        attachments.add(filename)
    # Standard markdown links: ![alt](path/to/image.png)
    md_matches = re.findall(r'!\[.*?\]\((.*?)\)', md_content)
    for match in md_matches:
        # Ignore external URLs
        if not match.startswith(("http://", "https://", "data:")):
            clean_path = match.split("#")[0].split("?")[0].strip()
            attachments.add(clean_path)
    return attachments

def locate_attachment_in_vault(ref: str, note_dir: Path) -> Path | None:
    """Find attachment in vault (relative to note or in Resources/Attachments)."""
    # 1. Direct path relative to note
    p1 = (note_dir / ref).resolve()
    if p1.is_file() and str(p1).startswith(str(VAULT_DIR)):
        return p1
    # 2. Relative to Vault root
    p2 = (VAULT_DIR / ref).resolve()
    if p2.is_file() and str(p2).startswith(str(VAULT_DIR)):
        return p2
    # 3. Inside Resources/Attachments
    p3 = (VAULT_DIR / "Resources" / "Attachments" / Path(ref).name).resolve()
    if p3.is_file():
        return p3
    # 4. Search recursively by basename
    target_name = Path(ref).name
    matches = list((VAULT_DIR / "Resources" / "Attachments").glob(f"**/{target_name}"))
    if matches:
        return matches[0]
    return None

def scan_vault():
    """Scan vault and return list of (note_path, relative_path)."""
    published_notes = []
    for root, dirs, files in os.walk(VAULT_DIR):
        # Filter ignored dirs
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not any(ign in os.path.join(root, d) for ign in IGNORED_DIRS)]
        for f in files:
            if f.endswith(".md"):
                file_path = Path(root) / f
                if is_published(file_path):
                    rel = file_path.relative_to(VAULT_DIR)
                    published_notes.append((file_path, rel))
    return published_notes

def sync_notes(dry_run=False):
    published = scan_vault()
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)

    synced_files = set()
    # Always keep index.md
    synced_files.add(CONTENT_DIR / "index.md")

    print(f"🌿 Tìm thấy {len(published)} ghi chú được đánh dấu `publish: true`:")
    for src, rel in published:
        dst = CONTENT_DIR / rel
        synced_files.add(dst)
        print(f"  • {rel}")

        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

            # Copy attachments referenced in note
            with open(src, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for ref in find_attachments(content):
                att_src = locate_attachment_in_vault(ref, src.parent)
                if att_src:
                    att_rel = att_src.relative_to(VAULT_DIR)
                    att_dst = CONTENT_DIR / att_rel
                    att_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(att_src, att_dst)
                    synced_files.add(att_dst)

    # Prune files in CONTENT_DIR that are no longer published
    if not dry_run:
        for root, dirs, files in os.walk(CONTENT_DIR):
            for f in files:
                target = Path(root) / f
                if target not in synced_files:
                    print(f"  🗑️ Xóa file không còn xuất bản: {target.relative_to(CONTENT_DIR)}")
                    target.unlink()
        # Clean empty folders
        for root, dirs, files in os.walk(CONTENT_DIR, topdown=False):
            for d in dirs:
                dir_path = Path(root) / d
                if not any(dir_path.iterdir()):
                    dir_path.rmdir()

    return len(published)

def main():
    parser = argparse.ArgumentParser(description="Sync published notes from Vault to Quartz")
    parser.add_argument("--status", action="store_true", help="List notes marked publish: true")
    parser.add_argument("--build", action="store_true", help="Build Quartz site after sync")
    parser.add_argument("--preview", action="store_true", help="Serve Quartz site locally after sync")
    parser.add_argument("--push", action="store_true", help="Commit and push to GitHub")
    args = parser.parse_args()

    if args.status:
        published = scan_vault()
        print(f"Hiện có {len(published)} ghi chú được đánh dấu `publish: true`:")
        for _, rel in published:
            print(f"  - {rel}")
        return

    count = sync_notes()
    print(f"✅ Đã đồng bộ {count} ghi chú sang {CONTENT_DIR.relative_to(QUARTZ_DIR.parent)}")

    if args.build:
        print("\n🔨 Đang build Quartz...")
        subprocess.run(["npx", "quartz", "build"], cwd=QUARTZ_DIR, check=True)

    if args.preview:
        print("\n🌐 Đang khởi động máy chủ xem trước...")
        subprocess.run(["npx", "quartz", "build", "--serve"], cwd=QUARTZ_DIR, check=True)

    if args.push:
        print("\n🚀 Đang đẩy lên GitHub...")
        subprocess.run(["git", "add", "."], cwd=QUARTZ_DIR, check=True)
        # Check if there are changes to commit
        status = subprocess.run(["git", "status", "--porcelain"], cwd=QUARTZ_DIR, capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", "Publish updates from Vault"], cwd=QUARTZ_DIR, check=True)
            subprocess.run(["git", "push"], cwd=QUARTZ_DIR, check=True)
            print("🎉 Đã đẩy thay đổi lên GitHub! GitHub Pages sẽ cập nhật sau ~1-2 phút.")
        else:
            print("Không có thay đổi mới để push.")

if __name__ == "__main__":
    main()
