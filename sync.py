#!/usr/bin/env python3
"""
Sync published notes from Obsidian Vault to Quartz Digital Garden.
Repository: https://github.com/itsdatlog/garden
Live Site:  https://itsdatlog.github.io/garden/

Usage:
    garden                  # Sync files from Vault to Quartz
    garden --status         # Check which notes are marked `publish: true`
    garden --preview        # Sync & preview locally at http://localhost:8080
    garden --build          # Sync & build static HTML
    garden --push           # Sync, build & publish to GitHub Pages
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
PUBLIC_DIR = QUARTZ_DIR / "public"
GITHUB_REPO_URL = "https://github.com/itsdatlog/garden.git"

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
        if not match.startswith(("http://", "https://", "data:")):
            clean_path = match.split("#")[0].split("?")[0].strip()
            attachments.add(clean_path)
    return attachments

def locate_attachment_in_vault(ref: str, note_dir: Path) -> Path | None:
    """Find attachment in vault (relative to note or in Resources/Attachments)."""
    p1 = (note_dir / ref).resolve()
    if p1.is_file() and str(p1).startswith(str(VAULT_DIR)):
        return p1
    p2 = (VAULT_DIR / ref).resolve()
    if p2.is_file() and str(p2).startswith(str(VAULT_DIR)):
        return p2
    p3 = (VAULT_DIR / "Resources" / "Attachments" / Path(ref).name).resolve()
    if p3.is_file():
        return p3
    target_name = Path(ref).name
    matches = list((VAULT_DIR / "Resources" / "Attachments").glob(f"**/{target_name}"))
    if matches:
        return matches[0]
    return None

def scan_vault():
    """Scan vault and return list of (note_path, relative_path)."""
    published_notes = []
    for root, dirs, files in os.walk(VAULT_DIR):
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

    if published:
        print(f"🌿 Tìm thấy {len(published)} ghi chú được đánh dấu `publish: true`:")
        for src, rel in published:
            dst = CONTENT_DIR / rel
            synced_files.add(dst)
            print(f"  • {rel}")

            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

                # Copy attachments
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
    else:
        print("ℹ️ Chưa có ghi chú nào trong Vault có `publish: true` (chỉ xuất bản trang chủ index.md).")

    # Prune files in CONTENT_DIR that are no longer published
    if not dry_run:
        for root, dirs, files in os.walk(CONTENT_DIR):
            for f in files:
                target = Path(root) / f
                if target not in synced_files:
                    print(f"  🗑️ Gỡ bỏ file không còn xuất bản: {target.relative_to(CONTENT_DIR)}")
                    target.unlink()
        # Clean empty folders
        for root, dirs, files in os.walk(CONTENT_DIR, topdown=False):
            for d in dirs:
                dir_path = Path(root) / d
                if not any(dir_path.iterdir()):
                    dir_path.rmdir()

    return len(published)

def build_site():
    print("\n🔨 Đang build Quartz...")
    subprocess.run(["npx", "quartz", "build"], cwd=QUARTZ_DIR, check=True)
    (PUBLIC_DIR / ".nojekyll").touch()

def deploy_to_github():
    print("\n🚀 Đang xuất bản lên GitHub Pages...")
    # 1. Push source updates to v5 branch
    subprocess.run(["git", "add", "."], cwd=QUARTZ_DIR, check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=QUARTZ_DIR, capture_output=True, text=True)
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", "Sync content and configuration"], cwd=QUARTZ_DIR, check=True)
        subprocess.run(["git", "push", "origin", "v5"], cwd=QUARTZ_DIR, check=True)

    # 2. Push built static HTML to gh-pages branch
    git_dir = PUBLIC_DIR / ".git"
    shutil.rmtree(git_dir, ignore_errors=True)
    subprocess.run(["git", "init"], cwd=PUBLIC_DIR, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "checkout", "-B", "gh-pages"], cwd=PUBLIC_DIR, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "add", "-A"], cwd=PUBLIC_DIR, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "commit", "-m", "Deploy to GitHub Pages"], cwd=PUBLIC_DIR, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "remote", "add", "origin", GITHUB_REPO_URL], cwd=PUBLIC_DIR, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "push", "-f", "origin", "gh-pages"], cwd=PUBLIC_DIR, check=True)
    shutil.rmtree(git_dir, ignore_errors=True)

    print("\n✨ XUẤT BẢN THÀNH CÔNG!")
    print("🌐 Trang web của bạn: https://itsdatlog.github.io/garden/")

def main():
    parser = argparse.ArgumentParser(description="Sync published notes from Vault to Quartz Digital Garden")
    parser.add_argument("--status", action="store_true", help="Kiểm tra các ghi chú đang có publish: true")
    parser.add_argument("--build", action="store_true", help="Đồng bộ và build static HTML")
    parser.add_argument("--preview", action="store_true", help="Đồng bộ và xem trước tại http://localhost:8080")
    parser.add_argument("--push", action="store_true", help="Đồng bộ, build và đẩy lên GitHub Pages")
    args = parser.parse_args()

    if args.status:
        published = scan_vault()
        if published:
            print(f"Hiện có {len(published)} ghi chú được đánh dấu `publish: true`:")
            for _, rel in published:
                print(f"  - {rel}")
        else:
            print("Chưa có ghi chú nào có `publish: true` trong Vault.")
        return

    count = sync_notes()

    if args.preview:
        print("\n🌐 Đang khởi động máy chủ xem trước...")
        subprocess.run(["npx", "quartz", "build", "--serve"], cwd=QUARTZ_DIR, check=True)
    elif args.push:
        build_site()
        deploy_to_github()
    elif args.build:
        build_site()
        print(f"✅ Đã build xong các file tĩnh tại {PUBLIC_DIR}")
    else:
        print(f"✅ Đã đồng bộ {count} ghi chú sang {CONTENT_DIR.relative_to(QUARTZ_DIR.parent)}")
        print("💡 Chạy `garden --preview` để xem thử trên máy, hoặc `garden --push` để xuất bản lên web.")

if __name__ == "__main__":
    main()
