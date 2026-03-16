"""Jinja2 template rendering for the static site."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def render_dashboard(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("dashboard.html")
    return tmpl.render(
        data=data,
        active_page="dashboard",
        static_prefix="",
        generated_at=data.get("generated_at", ""),
    )


def render_rising(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("rising.html")
    return tmpl.render(
        data=data, active_page="rising", static_prefix="", generated_at=data.get("generated_at", "")
    )


def render_leaderboard(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("leaderboard.html")
    return tmpl.render(
        data=data,
        active_page="leaderboard",
        static_prefix="",
        generated_at=data.get("generated_at", ""),
    )


def render_cohorts(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("cohorts.html")
    return tmpl.render(
        data=data,
        active_page="cohorts",
        static_prefix="",
        generated_at=data.get("generated_at", ""),
    )


def render_skill_detail(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("skill_detail.html")
    return tmpl.render(
        data=data, active_page="", static_prefix="../", generated_at=data.get("generated_at", "")
    )


def render_owner_detail(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("owner_detail.html")
    return tmpl.render(
        data=data, active_page="", static_prefix="../", generated_at=data.get("generated_at", "")
    )
