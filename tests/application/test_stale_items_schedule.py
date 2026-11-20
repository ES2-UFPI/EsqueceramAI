from pathlib import Path

from application.jobs.stale_items import main as stale_items_main


ROOT = Path(__file__).resolve().parents[2]


def test_render_yaml_defines_daily_stale_items_cron():
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "type: cron" in text
    assert "name: esqueceram-ai-stale-items" in text
    assert 'schedule: "0 3 * * *"' in text
    assert "python -m application.jobs.stale_items --json" in text


def test_github_workflow_defines_daily_stale_items_schedule():
    wf_path = ROOT / ".github" / "workflows" / "stale-items.yml"
    assert wf_path.exists()
    text = wf_path.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert 'cron: "0 3 * * *"' in text
    assert "workflow_dispatch:" in text
    assert "python -m application.jobs.stale_items --json" in text


def test_stale_items_cli_dry_run_succeeds(app, capsys):
    with app.app_context():
        rc = stale_items_main(["--dry-run", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"applied": false' in out
