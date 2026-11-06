"""把 GTNH-Huijiwiki-Editing 中的技能发布为维基页面。

用法：python scripts/publish_skills.py <Editing 仓库目录> [--dry-run]

每个技能目录 skills/<技能名>/ 发布为一组页面：
- SKILL.md → Project:编辑技能/<技能名>（技能首页，开头的 YAML 写进信息表）；
- 其他 .md 文件 → Project:编辑技能/<技能名>/<该文件的一级标题>。
正文由 pandoc 从 Markdown 转为 wikitext，并改写链接：
- 指向其他 .md 文件的相对链接 → 对应的维基页面；
- 指向脚本等其他文件的相对链接 → GitHub 上本次提交的文件；
- https://gtnh.huijiwiki.com/wiki/… 的链接 → 维基内部链接。
只写入 Project:编辑技能/ 之下的页面；内容未变时 MediaWiki 不会产生新版本。
"""

import os
import posixpath
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAGE_PREFIX = "Project:编辑技能/"
REPO_URL = "https://github.com/GTNH-Huijiwiki/GTNH-Huijiwiki-Editing"
WIKI_URL = "https://gtnh.huijiwiki.com/wiki/"
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
H1 = re.compile(r"\A\s*# ([^\n]+)\n")
MD_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\s]+)\)")
INLINE_CODE = re.compile(r"<code>(.*?)</code>", re.S)
ILLEGAL_TITLE = re.compile(r"[\[\]{}|<>#]")


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


class Skill:
    def __init__(self, root, name, sha):
        self.root, self.name, self.sha = root, name, sha
        self.base = PAGE_PREFIX + name
        self.docs = {}  # 相对路径 → {'title','heading','meta','body'}
        for folder, _, files in os.walk(root):
            for file in sorted(files):
                if not file.endswith(".md"):
                    continue
                rel = os.path.relpath(os.path.join(folder, file), root).replace(os.sep, "/")
                with open(os.path.join(folder, file), encoding="utf-8") as f:
                    meta, body = split_frontmatter(f.read().replace("\r\n", "\n"))
                match = H1.match(body)
                heading = match.group(1).strip() if match else posixpath.splitext(file)[0]
                body = body[match.end():] if match else body
                if rel == "SKILL.md":
                    title = self.base
                else:
                    if ILLEGAL_TITLE.search(heading):
                        raise ValueError(f"{rel} 的一级标题含有不能用于页面名的字符：{heading}")
                    title = f"{self.base}/{heading}"
                self.docs[rel] = {"title": title, "heading": heading, "meta": meta, "body": body}
        if "SKILL.md" not in self.docs:
            raise ValueError(f"{root} 缺少 SKILL.md")
        # 导航顺序：技能首页在前，其余按在 SKILL.md 中首次被链接的顺序排列。
        index_body = self.docs["SKILL.md"]["body"]
        def order(rel):
            if rel == "SKILL.md":
                return -1
            position = index_body.find("(" + rel)
            return position if position >= 0 else len(index_body)
        self.docs = dict(sorted(self.docs.items(), key=lambda item: (order(item[0]), item[0])))
        titles = [d["title"] for d in self.docs.values()]
        if len(set(titles)) != len(titles):
            raise ValueError(f"{name} 中有重复的一级标题，页面名会冲突")

    def link_target(self, current, target):
        """把 Markdown 链接目标换成维基页面名或外链。"""
        if target.startswith(WIKI_URL):
            path, _, anchor = target[len(WIKI_URL):].partition("#")
            title = urllib.parse.unquote(path).replace("_", " ")
            return title + ("#" + urllib.parse.unquote(anchor) if anchor else "")
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            return target
        path, _, anchor = target.partition("#")
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(current), path))
        if rel in self.docs:
            return self.docs[rel]["title"] + ("#" + anchor if anchor else "")
        if rel.startswith("../") or not os.path.exists(os.path.join(self.root, rel)):
            raise ValueError(f"{current} 中的链接指向不存在的文件：{target}")
        return f"{REPO_URL}/blob/{self.sha}/skills/{self.name}/{rel}"

    def to_wikitext(self, current, markdown):
        markdown = MD_LINK.sub(lambda m: f"[{m.group(1)}]({self.link_target(current, m.group(2))})", markdown)
        result = subprocess.run(
            ["pandoc", "--from", "gfm", "--to", "mediawiki", "--wrap", "none"],
            input=markdown, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        # pandoc 不转义行内代码里的 {{…}}、[[…]]，包一层 nowiki，避免在维基上被展开。
        return INLINE_CODE.sub(lambda m: "<code><nowiki>" + m.group(1) + "</nowiki></code>",
                               result.stdout).strip()

    def navigation(self, current):
        items = []
        for rel, doc in self.docs.items():
            label = "技能首页" if rel == "SKILL.md" else doc["heading"]
            items.append(f"'''{label}'''" if rel == current else f"[[{doc['title']}|{label}]]")
        return " · ".join(items)

    def pages(self):
        result = {}
        for rel, doc in self.docs.items():
            source = f"{REPO_URL}/blob/{self.sha}/skills/{self.name}/{rel}"
            parts = [
                "{{Mbox|type=info|text=本页由 [" + source + " GTNH-Huijiwiki-Editing 中的 "
                + rel + "] 自动同步，请到该仓库修改，直接编辑会在下次发布时被覆盖。<br>"
                + "本技能页面：" + self.navigation(rel) + "}}",
            ]
            if rel == "SKILL.md":
                parts += [
                    '{| class="wikitable side-head"',
                    f"! 技能名\n| <code>{doc['meta'].get('name', self.name)}</code>",
                    "|-",
                    f"! 用途\n| {doc['meta'].get('description', '')}",
                    "|-",
                    f"! 源文件\n| [{REPO_URL}/tree/{self.sha}/skills/{self.name} GitHub 上的完整技能目录]",
                    "|}",
                ]
            parts += ["", self.to_wikitext(rel, doc["body"]), ""]
            result[doc["title"]] = "\n".join(parts)
        return result


def collect_pages(editing_dir, sha):
    pages = {}
    skills_dir = os.path.join(editing_dir, "skills")
    for name in sorted(os.listdir(skills_dir)):
        root = os.path.join(skills_dir, name)
        if not os.path.isfile(os.path.join(root, "SKILL.md")):
            continue
        if not SKILL_NAME.match(name):
            raise ValueError(f"技能目录名只能用小写字母、数字和连字符：{name}")
        skill = Skill(root, name, sha)
        meta_name = skill.docs["SKILL.md"]["meta"].get("name")
        if meta_name and meta_name != name:
            raise ValueError(f"{name}/SKILL.md 的 name 与目录名不一致：{meta_name}")
        pages.update(skill.pages())
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

    # 文档改名或删除后，旧页面不会自动删除，这里列出来提醒维护者处理。
    existing = wiki._post({"action": "query", "list": "allpages", "apnamespace": "4",
                           "apprefix": PAGE_PREFIX.split(":", 1)[1], "aplimit": "500",
                           "format": "json"})["query"]["allpages"]
    stale = [p["title"] for p in existing
             if p["title"].split(":", 1)[1] not in {t.split(":", 1)[1] for t in pages}]
    if stale:
        print("以下页面已不对应任何技能文件，请人工确认后删除或改为重定向：")
        for title in stale:
            print("  " + title)


if __name__ == "__main__":
    main()
