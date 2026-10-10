#!/usr/bin/env python3
"""Seqwater AI demo installer: one command, any workspace, driven by a Databricks CLI profile.

    ./seqwater-demo install   --profile <profile> [--catalog main] [--schema seqwater_demo]
    ./seqwater-demo status    --profile <profile>
    ./seqwater-demo refresh   --profile <profile>     # re-run the daily data + insights job now
    ./seqwater-demo reset     --profile <profile>     # clear agent actions before a fresh demo run
    ./seqwater-demo uninstall --profile <profile>

Standard library only. Shells out to the Databricks CLI (bundles, apps, workspace, SQL) and the
Agent Bricks CLI (agent deploy). Settings from the last install are kept in .demo-state.<profile>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data_platform"
EXP = ROOT / "genie_experience"
AGENT_SRC = ROOT / "ops_agent"
SKILLS = ROOT / "skills"
BUILD = ROOT / ".build"
# The agent is deployed from a rendered copy OUTSIDE the repo: the deploy sync honours the repo's .gitignore,
# so a copy under the (ignored) .build/ folder would upload nothing.
AGENT_BUILD_ROOT = Path.home() / ".seqwater-demo" / "build"
AGENTBRICKS_VERSION = "0.5.0"
JOB_KEY = "seqwater_daily_refresh"
DEFAULTS = {"catalog": "main", "schema": "seqwater_demo", "app_name": "seqwater-ops",
            "llm_endpoint": "databricks-claude-sonnet-4-6", "agent_model": "system.ai.claude-sonnet-4-6"}

# ------------------------------------------------------------------ output helpers
BOLD, DIM, GREEN, RED, YELLOW, RESET = ("\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m") \
    if sys.stdout.isatty() else ("",) * 6


def step(n: int, total: int, msg: str) -> None:
    print(f"\n{BOLD}[{n}/{total}] {msg}{RESET}", flush=True)


def ok(msg: str) -> None:
    print(f"  {GREEN}✔{RESET} {msg}", flush=True)


def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}", flush=True)


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\n{RED}✘ {msg}{RESET}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------------ command runners
def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = True, check: bool = True,
        env: dict | None = None, drop: tuple = ()) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV" and k not in drop}
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, env=e)
    if check and p.returncode != 0:
        detail = ((p.stderr or "") + (p.stdout or "")).strip()[-2500:] if capture else ""
        die(f"Command failed: {' '.join(cmd[:4])} ...\n{detail}")
    return p


def dbx(profile: str, *args: str, cwd: Path | None = None, check: bool = True, as_json: bool = True,
        capture: bool = True):
    cmd = ["databricks", *args, "--profile", profile]
    if as_json and capture:
        cmd += ["-o", "json"]
    p = run(cmd, cwd=cwd, check=check, capture=capture)
    if as_json and capture and p.returncode == 0 and p.stdout.strip():
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            return p.stdout
    return p


def agentbricks_cmd() -> list[str]:
    if shutil.which("agentbricks"):
        return ["agentbricks"]
    if shutil.which("uvx"):
        return ["uvx", "--from", f"databricks-agentbricks=={AGENTBRICKS_VERSION}", "agentbricks"]
    die("The Agent Bricks CLI is not installed. Install uv (https://docs.astral.sh/uv/) or run: "
        f"pip install databricks-agentbricks=={AGENTBRICKS_VERSION}")
    return []


def agentbricks_auth(profile: str, host: str, host_has_path: bool) -> tuple[list[str], dict | None]:
    """CLI args and env for agentbricks. The Python SDK behind it keeps any path on a profile host
    (e.g. .../login.html) and builds broken URLs, so in that case authenticate with the bare host and
    a fresh OAuth token from the Databricks CLI instead of the profile."""
    if not host_has_path:
        return ["-p", profile], None
    tok = run(["databricks", "auth", "token", "--profile", profile, "-o", "json"], check=False)
    try:
        token = json.loads(tok.stdout)["access_token"]
    except Exception:
        die(f"Profile '{profile}' has a host with a path ({host}/...). Fix the host in ~/.databrickscfg "
            f"to just {host}, or re-run: databricks auth login --host {host} --profile {profile}")
    return [], {"DATABRICKS_HOST": host, "DATABRICKS_TOKEN": token, "DATABRICKS_AUTH_TYPE": "pat"}


def sql(profile: str, warehouse_id: str, statement: str, *, check: bool = True) -> list[list]:
    body = json.dumps({"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s",
                       "on_wait_timeout": "CONTINUE"})
    r = dbx(profile, "api", "post", "/api/2.0/sql/statements", "--json", body)
    while r.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = dbx(profile, "api", "get", f"/api/2.0/sql/statements/{r['statement_id']}")
    state = r.get("status", {}).get("state")
    if state != "SUCCEEDED":
        msg = r.get("status", {}).get("error", {}).get("message", state)
        if check:
            die(f"SQL failed: {statement[:120]}\n{msg}")
        warn(f"SQL warning: {msg[:200]}")
        return []
    return (r.get("result") or {}).get("data_array") or []


# ------------------------------------------------------------------ state
def state_path(profile: str) -> Path:
    return ROOT / f".demo-state.{re.sub(r'[^A-Za-z0-9_.-]', '_', profile)}.json"


def load_state(profile: str) -> dict:
    p = state_path(profile)
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(profile: str, st: dict) -> None:
    state_path(profile).write_text(json.dumps(st, indent=2))


# ------------------------------------------------------------------ preflight
def preflight(profile: str) -> dict:
    if not shutil.which("databricks"):
        die("The Databricks CLI is not on PATH. Install it: https://docs.databricks.com/dev-tools/cli/install.html")
    v = run(["databricks", "--version"]).stdout.strip()
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", v)
    if not m or (int(m.group(1)), int(m.group(2))) < (0, 292):
        die(f"Databricks CLI {v} is too old; v0.292+ (or v1.x) is required for Genie space bundles. Upgrade it.")
    ok(f"Databricks CLI {v}")
    me = dbx(profile, "current-user", "me", check=False)
    if not isinstance(me, dict) or "userName" not in me:
        die(f"Profile '{profile}' is not authenticated. Run: databricks auth login --profile {profile}")
    host = run(["databricks", "auth", "describe", "--profile", profile, "-o", "json"], check=False).stdout
    raw_host = ""
    try:
        raw_host = json.loads(host)["details"]["host"]
        u = urllib.parse.urlparse(raw_host)  # profiles sometimes carry a path, e.g. .../login.html
        host = f"{u.scheme}://{u.netloc}" if u.netloc else raw_host
    except Exception:
        host = ""
    ok(f"Signed in as {me['userName']} {DIM}{host}{RESET}")
    if sys.version_info < (3, 10):
        die("Python 3.10+ is required.")
    # the Databricks CLI reports a cleaned host; the Python SDK reads the raw value from the config file
    try:
        import configparser
        cfgp = configparser.ConfigParser()
        cfgp.read(os.environ.get("DATABRICKS_CONFIG_FILE", str(Path.home() / ".databrickscfg")))
        raw_host = cfgp.get(profile, "host", fallback=raw_host) or raw_host
    except Exception:
        pass
    path = urllib.parse.urlparse(raw_host).path if raw_host else ""
    return {"user": me["userName"], "host": host.rstrip("/"), "host_has_path": path not in ("", "/")}


def pick_warehouse(profile: str, requested: str | None) -> str:
    whs = dbx(profile, "warehouses", "list") or []
    if requested:
        if not any(w["id"] == requested for w in whs):
            die(f"Warehouse {requested} not found.")
        return requested
    ranked = sorted(whs, key=lambda w: (not w.get("enable_serverless_compute"), w.get("state") != "RUNNING", w["name"]))
    if not ranked:
        die("No SQL warehouse found. Create a serverless SQL warehouse, or pass --warehouse-id.")
    w = ranked[0]
    ok(f"SQL warehouse: {w['name']} ({w['id']}){'' if w.get('enable_serverless_compute') else ' - not serverless'}")
    return w["id"]


def workspace_default_catalog(profile: str, warehouse_id: str) -> str | None:
    """The workspace's default Unity Catalog catalog: metastore setting first, then the namespace setting, then SQL."""
    candidates = []
    ms = dbx(profile, "metastores", "current", check=False)
    if isinstance(ms, dict):
        candidates.append(ms.get("default_catalog_name"))
    ns = dbx(profile, "settings", "default-namespace", "get", check=False)
    if isinstance(ns, dict):
        candidates.append((ns.get("namespace") or {}).get("value"))
    rows = sql(profile, warehouse_id, "SELECT current_catalog()", check=False)
    candidates.append(rows[0][0] if rows and rows[0] else None)
    for c in candidates:
        if c and c not in ("hive_metastore", "spark_catalog") and isinstance(dbx(profile, "catalogs", "get", c, check=False), dict):
            return c
    return None


# ------------------------------------------------------------------ steps
def bundle_vars(cfg: dict, *names: str) -> list[str]:
    out = []
    for n in names:
        out += ["--var", f"{n}={cfg[n]}"]
    return out


def clean_bundle_cache(path: Path) -> None:
    # The workspace holds the authoritative bundle state; a stale local cache from another profile confuses it.
    shutil.rmtree(path / ".databricks", ignore_errors=True)


def deploy_data_platform(profile: str, cfg: dict) -> None:
    clean_bundle_cache(DATA)
    v = bundle_vars(cfg, "catalog", "schema", "llm_endpoint") + ["--var", f"refresh_schedule_status={cfg['schedule']}"]
    dbx(profile, "bundle", "deploy", *v, cwd=DATA, as_json=False)
    ok("Data platform bundle deployed (job: daily refresh + proactive insights)")
    info("Generating 2 years of synthetic operating data, metric views and today's insights (about 5-8 minutes)...")
    t0 = time.time()
    p = run(["databricks", "bundle", "run", JOB_KEY, *v, "--profile", profile], cwd=DATA, check=False)
    if p.returncode != 0:
        die("The data job failed. See the run in the workspace (Jobs > 'Seqwater AI demo - daily refresh').\n"
            + (p.stderr or p.stdout)[-1500:])
    ok(f"Data, metric views and proactive insights ready ({int(time.time() - t0)}s)")


def deploy_experience(profile: str, cfg: dict) -> str:
    clean_bundle_cache(EXP)
    run([sys.executable, str(EXP / "build_space.py"), "--catalog", cfg["catalog"], "--schema", cfg["schema"]])
    v = bundle_vars(cfg, "catalog", "schema", "warehouse_id")
    dbx(profile, "bundle", "deploy", *v, cwd=EXP, as_json=False)
    summary = dbx(profile, "bundle", "summary", *v, cwd=EXP)
    space_id = summary["resources"]["genie_spaces"]["seqwater_ops"]["id"]
    ok(f"Genie space 'Seqwater Operations Intelligence' ({space_id})")
    ok("SQL alert 'Seqwater - critical operational insight raised' (emails you at 5:30am when Critical items exist)")
    return space_id


def install_skills(profile: str, cfg: dict, user: str) -> list[str]:
    fq = f"{cfg['catalog']}.{cfg['schema']}"
    names = []
    for d in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").exists()):
        out = BUILD / "skills" / d.name
        out.mkdir(parents=True, exist_ok=True)
        (out / "SKILL.md").write_text((d / "SKILL.md").read_text().replace("{{fq}}", fq))
        target = f"/Users/{user}/.assistant/skills/{d.name}"
        dbx(profile, "workspace", "mkdirs", target, as_json=False)
        dbx(profile, "workspace", "import", f"{target}/SKILL.md", "--file", str(out / "SKILL.md"),
            "--format", "AUTO", "--overwrite", as_json=False)
        names.append(d.name)
    ok(f"Genie One skills installed for {user}: {', '.join(names)}")
    return names


def render_agent(cfg: dict, profile: str, space_id: str) -> Path:
    dest = AGENT_BUILD_ROOT / re.sub(r"[^A-Za-z0-9_.-]", "_", profile) / "ops_agent"
    dest.parent.mkdir(parents=True, exist_ok=True)
    keep = {}
    for f in ("app.yaml", "agent.toml"):  # keep what agentbricks recorded on the previous deploy
        if (dest / f).exists():
            keep[f] = (dest / f).read_text()
    ignore = shutil.ignore_patterns(".venv", ".databricks", "__pycache__", "mlartifacts", "mlflow*", ".env",
                                    "app.agentbricksdev.yaml", ".pytest_cache", "uv.lock")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(AGENT_SRC, dest, ignore=ignore)
    app = (dest / "app.yaml").read_text()
    app = (app.replace('value: "main"', f'value: "{cfg["catalog"]}"')
              .replace('value: "seqwater_demo"', f'value: "{cfg["schema"]}"')
              .replace("__WAREHOUSE_ID__", cfg["warehouse_id"]))
    toml = (dest / "agent.toml").read_text().replace("00000000000000000000000000000000", space_id)
    if "agent.toml" in keep:  # carry the recorded deployment name forward
        m = re.search(r'deployment_name = "([^"]+)"', keep["agent.toml"])
        if m and m.group(1) == cfg["app_name"]:
            toml = toml.replace('server = "agentbricks"', f'server = "agentbricks"\ndeployment_name = "{m.group(1)}"')
    (dest / "app.yaml").write_text(app)
    (dest / "agent.toml").write_text(toml)
    agent_py = dest / "agent" / "agent.py"
    agent_py.write_text(re.sub(r'^MODEL = ".*"$', f'MODEL = "{cfg["agent_model"]}"', agent_py.read_text(), flags=re.M))
    # local dev settings go in .env.local-dev (never synced); `agentbricks dev -p <profile>` supplies auth
    (dest / ".env.local-dev").write_text(
        f"SEQWATER_CATALOG={cfg['catalog']}\nSEQWATER_SCHEMA={cfg['schema']}\nSEQWATER_WAREHOUSE_ID={cfg['warehouse_id']}\n")
    return dest


def deploy_agent(profile: str, cfg: dict, space_id: str, host: str = "", host_has_path: bool = False) -> dict:
    src = render_agent(cfg, profile, space_id)
    ab = agentbricks_cmd()
    info("Deploying the Seqwater Operations Agent to Databricks Apps (about 3-6 minutes)...")
    auth_args, env = agentbricks_auth(profile, host, host_has_path)
    p = run([*ab, *auth_args, "deploy", cfg["app_name"], "--source", str(src)], check=False, env=env,
            drop=("DATABRICKS_CONFIG_PROFILE",) if env else ())
    if p.returncode != 0:
        die("Agent deploy failed:\n" + ((p.stderr or "") + (p.stdout or ""))[-2500:])
    name = cfg["app_name"].removeprefix("agent-bricks-")
    app_name = f"agent-bricks-{name}"
    app = dbx(profile, "apps", "get", app_name)
    sp = app.get("service_principal_client_id")
    ok(f"Agent app '{app_name}' running: {app.get('url')}")
    # least-privilege grants for the app's service principal (Genie CAN_RUN and model EXECUTE are done by agentbricks)
    cat, sch, wh = cfg["catalog"], cfg["schema"], cfg["warehouse_id"]
    for stmt in (f"GRANT USE CATALOG ON CATALOG `{cat}` TO `{sp}`",
                 f"GRANT USE SCHEMA, SELECT ON SCHEMA `{cat}`.`{sch}` TO `{sp}`",
                 f"GRANT MODIFY ON TABLE `{cat}`.`{sch}`.agent_actions TO `{sp}`"):
        sql(profile, wh, stmt)
    # the agent's model: agentbricks grants EXECUTE for the MODEL literal; some workspaces also lock down system.ai
    model_schema, model_name = cfg["agent_model"].rsplit(".", 1)
    sql(profile, wh, f"GRANT USE SCHEMA ON SCHEMA {model_schema} TO `{sp}`", check=False)
    sql(profile, wh, f"GRANT EXECUTE ON MODEL SERVICE {model_schema}.`{model_name}` TO `{sp}`", check=False)
    dbx(profile, "warehouses", "update-permissions", wh, "--json",
        json.dumps({"access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_USE"}]}))
    ok("App service principal granted: read the demo schema, write agent_actions, use the warehouse")
    return {"agent_app": app_name, "app_url": app.get("url"), "app_sp": sp}


def warm_up_agent(profile: str, url: str) -> None:
    """Ask the deployed agent a trivial question until it answers (new grants can take a minute or two)."""
    tok = run(["databricks", "auth", "token", "--profile", profile, "-o", "json"], check=False)
    try:
        token = json.loads(tok.stdout)["access_token"]
    except Exception:
        warn("Could not get an OAuth token to warm up the agent; open the Command Centre once before the demo.")
        return
    body = json.dumps({"id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()),
                       "input": {"messages": [{"role": "user", "content": "Reply with the single word READY."}]}}).encode()
    for attempt in range(1, 7):
        req = urllib.request.Request(f"{url}/api/invocations", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read().decode())
            if out.get("status") == "completed" or "READY" in json.dumps(out):
                ok("Agent answered a warm-up question: model, tools and permissions are working")
                return
        except Exception as e:  # 5xx while grants propagate
            info(f"warm-up attempt {attempt}: not ready yet ({str(e)[:80]})")
        body = json.dumps({**json.loads(body), "id": str(uuid.uuid4())}).encode()
        time.sleep(30)
    warn("The agent did not answer yet. Wait a few minutes, then check: agentbricks deployments logs "
         "<app> (a 'model does not exist' error means the app needs EXECUTE on the model; see RUNBOOK troubleshooting).")


# ------------------------------------------------------------------ commands
def cmd_install(a) -> None:
    total = 6
    step(1, total, "Checking prerequisites")
    who = preflight(a.profile)
    prev = load_state(a.profile)
    cfg = {k: getattr(a, k) or prev.get(k) or DEFAULTS.get(k) for k in ("catalog", "schema", "app_name", "llm_endpoint", "agent_model")}
    cfg["schedule"] = "PAUSED" if a.no_schedule else "UNPAUSED"
    cfg["warehouse_id"] = pick_warehouse(a.profile, a.warehouse_id or prev.get("warehouse_id"))
    if not isinstance(dbx(a.profile, "catalogs", "get", cfg["catalog"], check=False), dict):
        if a.catalog:
            die(f"Catalog '{cfg['catalog']}' not found or not accessible. Pass --catalog <one you can create schemas in>.")
        # no `main` here: fall back to the workspace's default catalog (FEVM and many newer workspaces)
        default = workspace_default_catalog(a.profile, cfg["warehouse_id"])
        if not default:
            die(f"Catalog '{cfg['catalog']}' not found and the workspace has no default Unity Catalog catalog. Pass --catalog <name>.")
        info(f"No '{cfg['catalog']}' catalog in this workspace; using the workspace default catalog '{default}'")
        cfg["catalog"] = default
    ok(f"Target schema: {cfg['catalog']}.{cfg['schema']}")
    if not a.skip_agent:
        agentbricks_cmd()
    st = {**prev, **cfg, **who, "profile": a.profile}
    save_state(a.profile, st)

    step(2, total, "Data platform: synthetic Seqwater data, metric views, proactive insights")
    if a.skip_data:
        info("skipped (--skip-data)")
    else:
        deploy_data_platform(a.profile, cfg)

    step(3, total, "Genie experience: Genie space and SQL alert")
    st["genie_space_id"] = deploy_experience(a.profile, cfg)
    save_state(a.profile, st)

    step(4, total, "Genie One skills")
    st["skills"] = install_skills(a.profile, cfg, who["user"])

    step(5, total, "Agent Bricks: Seqwater Operations Agent + Ops Command Centre app")
    if a.skip_agent:
        info("skipped (--skip-agent)")
    else:
        st.update(deploy_agent(a.profile, cfg, st["genie_space_id"], who["host"], who.get("host_has_path", False)))
        save_state(a.profile, st)
        warm_up_agent(a.profile, st["app_url"])
    save_state(a.profile, st)

    step(6, total, "Ready")
    print_links(st)


def print_links(st: dict) -> None:
    host = st.get("host", "")
    print(f"""
  {BOLD}Genie One (start the demo here){RESET}     {host}/one
  {BOLD}Ops Command Centre app{RESET}              {st.get('app_url', '(agent not deployed)')}
  {BOLD}Genie space{RESET}                         {host}/genie/rooms/{st.get('genie_space_id', '')}
  {BOLD}Data (Catalog Explorer){RESET}             {host}/explore/data/{st.get('catalog')}/{st.get('schema')}
  {BOLD}Skills{RESET}                              {', '.join('/' + s for s in st.get('skills', []))}

  {BOLD}Before the meeting{RESET} (5 minutes, see docs/RUNBOOK.md):
   1. In Genie One, run:  /seqwater-morning-briefing
   2. Create the scheduled task: Genie One > Schedules > "Seqwater Morning Operations Briefing", weekdays 6:30am.
   3. Open the Ops Command Centre once so the app is warm.
""")


def cmd_status(a) -> None:
    st = load_state(a.profile)
    if not st:
        die(f"No install found for profile '{a.profile}'. Run: ./seqwater-demo install --profile {a.profile}")
    fq = f"`{st['catalog']}`.`{st['schema']}`"
    rows = sql(a.profile, st["warehouse_id"],
               f"SELECT (SELECT data_through_date FROM {fq}.demo_metadata), (SELECT COUNT(*) FROM {fq}.proactive_insights), "
               f"(SELECT MAX(generated_at) FROM {fq}.daily_briefing), (SELECT COUNT(*) FROM {fq}.agent_actions)", check=False)
    if rows:
        d, n, g, acts = rows[0]
        ok(f"Data through {d} · {n} proactive insights · briefing generated {g} UTC · {acts} agent actions")
    if st.get("agent_app"):
        app = dbx(a.profile, "apps", "get", st["agent_app"], check=False)
        if isinstance(app, dict):
            ok(f"App {st['agent_app']}: {app.get('compute_status', {}).get('state')} / {app.get('app_status', {}).get('state')}")
    print_links(st)


def cmd_refresh(a) -> None:
    st = load_state(a.profile) or die("Run install first.")
    v = bundle_vars(st, "catalog", "schema", "llm_endpoint")
    info("Running the daily refresh job now...")
    dbx(a.profile, "bundle", "run", JOB_KEY, *v, cwd=DATA, as_json=False)
    ok("Data and proactive insights refreshed")


def cmd_reset(a) -> None:
    st = load_state(a.profile) or die("Run install first.")
    fq = f"`{st['catalog']}`.`{st['schema']}`"
    sql(a.profile, st["warehouse_id"], f"DELETE FROM {fq}.agent_actions")
    sql(a.profile, st["warehouse_id"], f"DELETE FROM {fq}.work_orders WHERE source_system = 'Seqwater Operations Agent'")
    sql(a.profile, st["warehouse_id"], f"UPDATE {fq}.reservoir_offtakes SET in_service = (offtake_level = 'Upper')", check=False)
    ok("Agent actions and agent-raised work orders cleared: the demo starts clean")


def cmd_uninstall(a) -> None:
    st = load_state(a.profile) or die("Nothing to uninstall for this profile.")
    if not a.yes:
        print(f"This deletes the agent app, both bundles, the skills and the schema {st['catalog']}.{st['schema']}.")
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            die("Cancelled.")
    if st.get("agent_app"):
        auth_args, env = agentbricks_auth(a.profile, st.get("host", ""), st.get("host_has_path", False))
        run([*agentbricks_cmd(), *auth_args, "deployments", "delete", st["agent_app"]], check=False, env=env,
            drop=("DATABRICKS_CONFIG_PROFILE",) if env else ())
        ok(f"Deleted app {st['agent_app']}")
    v_exp = bundle_vars(st, "catalog", "schema", "warehouse_id")
    run([sys.executable, str(EXP / "build_space.py"), "--catalog", st["catalog"], "--schema", st["schema"]])
    dbx(a.profile, "bundle", "destroy", "--auto-approve", *v_exp, cwd=EXP, as_json=False, check=False)
    ok("Destroyed Genie space and alert")
    dbx(a.profile, "bundle", "destroy", "--auto-approve", *bundle_vars(st, "catalog", "schema", "llm_endpoint"),
        cwd=DATA, as_json=False, check=False)
    ok("Destroyed data platform job")
    for s in st.get("skills", []):
        dbx(a.profile, "workspace", "delete", "--recursive", f"/Users/{st['user']}/.assistant/skills/{s}", as_json=False, check=False)
    ok("Removed skills")
    sql(a.profile, st["warehouse_id"], f"DROP SCHEMA IF EXISTS `{st['catalog']}`.`{st['schema']}` CASCADE", check=False)
    ok(f"Dropped schema {st['catalog']}.{st['schema']}")
    state_path(a.profile).unlink(missing_ok=True)
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(AGENT_BUILD_ROOT / re.sub(r"[^A-Za-z0-9_.-]", "_", a.profile), ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="seqwater-demo", description="Seqwater AI demo on Databricks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("install", help="deploy everything to a workspace")
    for p in [pi] + [sub.add_parser(n, help=h) for n, h in (("status", "show what is deployed"),
                                                           ("refresh", "re-run the data + insights job now"),
                                                           ("reset", "clear agent actions before a demo"),
                                                           ("uninstall", "remove everything"))]:
        p.add_argument("-p", "--profile", required=True, help="Databricks CLI profile (~/.databrickscfg)")
        if p.prog.endswith("uninstall"):
            p.add_argument("--yes", action="store_true", help="do not prompt")
    pi.add_argument("--catalog", help="catalog for the demo schema (default: main)")
    pi.add_argument("--schema", help="demo schema (default: seqwater_demo)")
    pi.add_argument("--warehouse-id", help="SQL warehouse id (default: first serverless warehouse)")
    pi.add_argument("--app-name", help="agent name; the app is agent-bricks-<name> (default: seqwater-ops)")
    pi.add_argument("--llm-endpoint", help="endpoint ai_query uses for insight narratives (default: databricks-claude-sonnet-4-6)")
    pi.add_argument("--agent-model", help="AI Gateway model for the agent (default: system.ai.claude-sonnet-4-6)")
    pi.add_argument("--no-schedule", action="store_true", help="leave the daily 5:15am refresh paused")
    pi.add_argument("--skip-data", action="store_true", help="skip regenerating data (re-deploy the rest only)")
    pi.add_argument("--skip-agent", action="store_true", help="skip the Agent Bricks app")
    a = ap.parse_args()
    {"install": cmd_install, "status": cmd_status, "refresh": cmd_refresh, "reset": cmd_reset,
     "uninstall": cmd_uninstall}[a.cmd](a)


if __name__ == "__main__":
    main()
