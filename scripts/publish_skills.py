"""把 GTNH-Huijiwiki-Editing 中的技能发布为维基页面。

用法：python scripts/publish_skills.py <Editing 仓库目录> [--dry-run]

每个 skills/<技能名>/SKILL.md 发布为 Project:编辑技能/<技能名>：
开头的 YAML 写进信息表，正文由 pandoc 从 Markdown 转为 wikitext。
只写入 Project:编辑技能/ 之下的页面；内容未变时 MediaWiki 不会产生新版本。
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAGE_PREFIX = "Project:编辑技能/"
REPO_URL = "https://github.com/GTNH-Huijiwiki/GTNH-Huijiwiki-Editing"
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def split_frontmatter(text):
    """拆出开头 --- 包围的 YAML，只支持 key: value 单行写法。"""
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                key, sep, value = line.partition(":")
                if sep:
                    meta[key.strip()] = value.strip().strip('"\'')
            text = text[end + len("\n---\n"):]
    return meta, text


LEADING_H1 = re.compile(r"\A\s*# [^\n]*\n")
INLINE_CODE = re.compile(r"<code>(.*?)</code>", re.S)


def markdown_to_wikitext(markdown):
    # 正文开头的一级标题与页面标题重复，发布时去掉。
    markdown = LEADING_H1.sub("", markdown, count=1)
    result = subprocess.run(
        ["pandoc", "--from", "gfm", "--to", "mediawiki", "--wrap", "none"],
        input=markdown, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    # pandoc 不转义行内代码里的 {{…}}、[[…]]，包一层 nowiki，避免在维基上被展开。
    return INLINE_CODE.sub(lambda m: "<code><nowiki>" + m.group(1) + "</nowiki></code>",
                           result.stdout).strip()


def build_page(name, meta, body, sha):
    source = f"{REPO_URL}/tree/{sha}/skills/{name}"
    return "\n".join([
        "{{Mbox|type=info|text=本页由 [" + source + " GTNH-Huijiwiki-Editing] 自动同步，"
        "请到该仓库修改，直接编辑会在下次发布时被覆盖。}}",
        '{| class="wikitable side-head"',
        f"! 技能名\n| <code>{meta.get('name', name)}</code>",
        "|-",
        f"! 用途\n| {meta.get('description', '')}",
        "|}",
        "",
        markdown_to_wikitext(body),
        "",
    ])


def collect_pages(editing_dir, sha):
    pages = {}
    skills_dir = os.path.join(editing_dir, "skills")
    for name in sorted(os.listdir(skills_dir)):
        path = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        if not SKILL_NAME.match(name):
            raise ValueError(f"技能目录名只能用小写字母、数字和连字符：{name}")
        with open(path, encoding="utf-8") as f:
            meta, body = split_frontmatter(f.read().replace("\r\n", "\n"))
        if meta.get("name") and meta["name"] != name:
            raise ValueError(f"{path} 的 name 与目录名不一致：{meta['name']}")
        pages[PAGE_PREFIX + name] = build_page(name, meta, body, sha)
    return pages


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    editing_dir = args[0] if args else "editing"
    sha = subprocess.run(["git", "-C", editing_dir, "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    pages = collect_pages(editing_dir, sha)
    print(f"共 {len(pages)} 个技能页面，来源提交 {sha[:7]}")

    if dry_run:
        for title, text in pages.items():
            print(f"===== {title}\n{text}")
        return

    import wiki
    bot_user = os.environ.get("BOT_USERNAME", "")
    bot_pass = os.environ.get("BOT_PASSWORD", "")
    if not (bot_user and bot_pass):
        raise RuntimeError("缺少 BOT_USERNAME 或 BOT_PASSWORD")
    wiki.login(bot_user, bot_pass)
    me = wiki._get({"action": "query", "meta": "userinfo", "format": "json"})["query"]["userinfo"]["name"]
    if me != bot_user:
        raise RuntimeError(f"登录账号不符：API 返回 {me}")

    for title, text in pages.items():
        assert title.startswith(PAGE_PREFIX), title
        wiki.edit_page(title, text, summary=f"同步编辑技能（GTNH-Huijiwiki-Editing@{sha[:7]}）", bot=True)
        wiki._post({"action": "purge", "titles": title, "format": "json"})


if __name__ == "__main__":
    main()
