# -*- coding: utf-8 -*-
"""
纯标准库 GitHub 初始化脚本
用法示例：
  export GH_TOKEN=ghp_xxx
  export GH_REPO=owner/repo
  python tools/bootstrap_github.py --create-all
或分别：
  python tools/bootstrap_github.py --labels
  python tools/bootstrap_github.py --milestones
  python tools/bootstrap_github.py --epics
"""
import os, sys, json, urllib.request, urllib.error, urllib.parse, argparse, subprocess

API = "https://api.github.com"

def repo_from_env():
    repo = os.getenv("GH_REPO")
    if repo:
        return repo
    # 尝试从 git remote 解析
    try:
        url = subprocess.check_output(["git","config","--get","remote.origin.url"], text=True).strip()
        # 支持 git@github.com:owner/repo.git 或 https://github.com/owner/repo.git
        if url.startswith("git@github.com:"):
            return url.split("git@github.com:")[1].removesuffix(".git")
        if "github.com/" in url:
            return url.split("github.com/")[1].removesuffix(".git")
    except Exception:
        pass
    raise SystemExit("无法确定仓库。请设置环境变量 GH_REPO=owner/repo")

def auth_headers():
    token = os.getenv("GH_TOKEN")
    if not token:
        raise SystemExit("缺少 GH_TOKEN。请 export GH_TOKEN=你的GitHub PAT（需要 repo 权限）")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
    }

def api_get(path):
    req = urllib.request.Request(API+path, headers=auth_headers())
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())

def api_post(path, data):
    req = urllib.request.Request(API+path, headers=auth_headers(), method="POST", data=json.dumps(data).encode())
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())

def api_patch(path, data):
    req = urllib.request.Request(API+path, headers=auth_headers(), method="PATCH", data=json.dumps(data).encode())
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())

def ensure_labels(repo, labels):
    existing = {x["name"]:x for x in api_get(f"/repos/{repo}/labels?per_page=200")}
    for lb in labels:
        name = lb["name"]
        if name in existing:
            api_patch(f"/repos/{repo}/labels/{urllib.parse.quote(name)}",
                      {"new_name": name, "color": lb["color"], "description": lb.get("description","")})
            print(f"[OK] label updated: {name}")
        else:
            api_post(f"/repos/{repo}/labels", lb)
            print(f"[OK] label created: {name}")

def ensure_milestones(repo, milestones):
    exist = api_get(f"/repos/{repo}/milestones?state=all&per_page=100")
    titles = {m["title"]:m for m in exist}
    for m in milestones:
        title = m["title"]
        if title in titles:
            print(f"[SKIP] milestone exists: {title}")
        else:
            api_post(f"/repos/{repo}/milestones", {"title": title, "state": m.get("state","open"), "description": m.get("description","")})
            print(f"[OK] milestone created: {title}")

def milestone_number(repo, title):
    for m in api_get(f"/repos/{repo}/milestones?state=all&per_page=100"):
        if m["title"] == title:
            return m["number"]
    return None

def list_issues_titles(repo):
    # 拉取前 300 条（足够初始化用）
    titles = set()
    page = 1
    while page <= 3:
        arr = api_get(f"/repos/{repo}/issues?state=all&per_page=100&page={page}")
        if not arr: break
        for i in arr:
            titles.add(i["title"])
        page += 1
    return titles

def create_epics(repo, epics):
    exists = list_issues_titles(repo)
    for e in epics:
        title = e["title"]
        if title in exists:
            print(f"[SKIP] epic exists: {title}")
            continue
        ms_num = milestone_number(repo, e["milestone"])
        data = {
            "title": title,
            "body": e.get("body",""),
            "labels": e.get("labels",[])
        }
        if ms_num: data["milestone"] = ms_num
        api_post(f"/repos/{repo}/issues", data)
        print(f"[OK] epic created: {title}")

def load_seed():
    base = os.path.join("tools","github_seed")
    with open(os.path.join(base,"labels.json"),"r",encoding="utf-8") as f:
        labels = json.load(f)
    with open(os.path.join(base,"milestones.json"),"r",encoding="utf-8") as f:
        milestones = json.load(f)
    with open(os.path.join(base,"epics.json"),"r",encoding="utf-8") as f:
        epics = json.load(f)
    return labels, milestones, epics

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--labels", action="store_true")
    p.add_argument("--milestones", action="store_true")
    p.add_argument("--epics", action="store_true")
    p.add_argument("--create-all", action="store_true")
    args = p.parse_args()

    repo = repo_from_env()
    labels, milestones, epics = load_seed()

    if args.create_all or (not any([args.labels,args.milestones,args.epics])):
        args.labels = args.milestones = args.epics = True

    if args.labels:
        ensure_labels(repo, labels)
    if args.milestones:
        ensure_milestones(repo, milestones)
    if args.epics:
        ensure_milestones(repo, milestones)  # 确保里程碑已存在
        create_epics(repo, epics)

if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print("HTTPError:", e.read().decode(), file=sys.stderr)
        raise

