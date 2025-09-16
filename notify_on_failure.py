#!/usr/bin/env python3

"""
notify_on_failure.py
- Looks up the last committer's email for CI_COMMIT_SHA
- Maps email -> Slack user (via optional mapping JSON or Slack users.lookupByEmail)
- Opens a DM and posts a failure message with pipeline context
- Falls back to SLACK_FALLBACK_CHANNEL if DM can't be sent

Env vars the script uses:
  Required:
    SLACK_BOT_TOKEN
  Optional:
    SLACK_FALLBACK_CHANNEL      e.g. "#ci-failures" or "C012ABCDEF0"
    SLACK_MAPPINGS_JSON         JSON: {"email_to_user_id":{"alice@x.com":"U123","bob@x.com":"U456"}}
    NOTIFY_BRANCH_REGEX         Regex of branches to notify on (default: ".*")

  Provided by GitLab CI (automatically):
    CI_PROJECT_PATH, CI_PROJECT_NAMESPACE, CI_PROJECT_NAME
    CI_COMMIT_SHA, CI_COMMIT_REF_NAME, CI_COMMIT_TITLE
    CI_PIPELINE_ID, CI_PIPELINE_URL
    CI_COMMIT_AUTHOR, GITLAB_USER_EMAIL
"""

import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
SLACK_API_BASE = "https://slack.com/api"
TIMEOUT = 30

def getenv(name, default=None):
    return os.environ.get(name, default)


def run_git_show_email(commit_sha):
    try:
        out = subprocess.check_output(
            ["git", "show", "-s", "--format=%ae", commit_sha],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return ""


def parse_email_from_ci_commit_author(s):
    # CI_COMMIT_AUTHOR often looks like: "Name <email@domain>"
    if not s:
        return ""
    m = re.search(r"<([^>]+)>", s)
    return m.group(1).strip() if m else ""



def lookup_user_id_by_email(client, email):
    #TODO:
    # email = "manuel+slack@strenge.ch"
    if not email:
        return ""
    try:
        response = client.users_lookupByEmail(
            email=email,
        )
    except SlackApiError as e:
        assert e.response["error"]
        print(f"Slack email lookup failed: {e}", file=sys.stderr)
        return ""
    return response["user"]["id"]


def open_dm(client, user_id):
    try:
        response = client.conversations_open(
            users=user_id,
            prevent_creation=False,
        )
    except SlackApiError as e:
        print(f"conversations.open error: {e}", file=sys.stderr)
        assert e.response["error"]
        return ""
    return response["channel"]["id"]


def post_message(client, channel, text, blocks=None):
    try:
        response = client.chat_postMessage(
            channel="ci",
            text=text,
            blocks=blocks
        )
    except SlackApiError as e:
        assert e.response["error"]
        print(response)
        return False
    return True


def load_mapping_user_id(email):
    mapping_raw = getenv("SLACK_MAPPINGS_JSON", "")
    if not mapping_raw or not email:
        return ""
    try:
        mapping = json.loads(mapping_raw)
        return mapping.get("email_to_user_id", {}).get(email, "") or ""
    except Exception as e:
        print(f"SLACK_MAPPINGS_JSON parse error: {e}", file=sys.stderr)
        return ""


def main():
    token = getenv("SLACK_BOT_TOKEN", "")
    client = WebClient(token=token)


    if not token:
        print("SLACK_BOT_TOKEN is not set; exiting.", file=sys.stderr)
        return 0  # exit gracefully so CI job doesn't hard-fail

    branch = getenv("CI_COMMIT_REF_NAME", "unknown")
    branch_regex = getenv("NOTIFY_BRANCH_REGEX", ".*")
    if not re.search(branch_regex, branch):
        print(f"Branch '{branch}' does not match NOTIFY_BRANCH_REGEX; skipping.")
        return 0

    # Determine author email
    commit_sha = getenv("CI_COMMIT_SHA", "")
    author_email = run_git_show_email(commit_sha)
    if not author_email:
        author_email = parse_email_from_ci_commit_author(getenv("CI_COMMIT_AUTHOR", ""))
    if not author_email:
        author_email = getenv("GITLAB_USER_EMAIL", "")

    if author_email:
        print(f"Commit author email: {author_email}")
    else:
        print("Could not determine author email; will use fallback channel.", file=sys.stderr)

    project_path = getenv("CI_PROJECT_PATH") or f"{getenv('CI_PROJECT_NAMESPACE','')}/{getenv('CI_PROJECT_NAME','')}"
    short_sha = (commit_sha or "unknown")[:8]
    pipeline_id = getenv("CI_PIPELINE_ID", "")
    pipeline_url = getenv("CI_PIPELINE_URL", "")
    commit_title = getenv("CI_COMMIT_TITLE", "(no title)")

    summary = f"A job failed in pipeline {pipeline_id} for {project_path}"
    if pipeline_url:
        summary += f" → {pipeline_url}"

    # Slack Block Kit for a clean layout
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Pipeline failed", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Project:* {project_path}"},
                {"type": "mrkdwn", "text": f"*Branch:* {branch}"},
                {"type": "mrkdwn", "text": f"*Commit:* `{short_sha}`"},
                {"type": "mrkdwn", "text": f"*Author:* {author_email or 'unknown'}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Commit title:* {commit_title}"},
        },
    ]
    if pipeline_url:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"<{pipeline_url}|Open the failed pipeline>"}}
        )

    # Resolve Slack user
    slack_user_id = ""
    if author_email:
        slack_user_id = load_mapping_user_id(author_email) or lookup_user_id_by_email(client,  author_email)

    # Try DM first
    if slack_user_id:
        channel_id = open_dm(client, slack_user_id)
        if channel_id and post_message(client, channel_id, summary, blocks=blocks):
            print("DM sent successfully.")
            return 0
        else:
            print("DM failed; will try fallback channel.", file=sys.stderr)
    else:
        print("No Slack user id resolved; will try fallback channel.", file=sys.stderr)

    # Fallback to channel
    fallback = getenv("SLACK_FALLBACK_CHANNEL", "")
    if fallback:
        ok = post_message(client, fallback, f"{summary} (author: {author_email or 'unknown'})", blocks=blocks)
        print("Posted to fallback channel." if ok else "Posting to fallback channel failed.", file=sys.stderr)
        return 0
    else:
        print("SLACK_FALLBACK_CHANNEL not set; nothing else to do.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    # Optional: make git directory "safe" for CI containers where uid differs
    try:
        proj_dir = os.environ.get("CI_PROJECT_DIR")
        if proj_dir:
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", proj_dir], check=False)
            # try to unshallow to ensure 'git show' works
            subprocess.run(["git", "fetch", "--unshallow"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    sys.exit(main())

