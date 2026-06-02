#!/usr/bin/env python3
"""
Shared script for DeepSeek code review.
Called by GitHub Actions workflows with the diff content and optional user instructions.
"""

import json
import os
import sys
import urllib.request
import urllib.error


def get_env_or_fail(key: str) -> str:
    """Get a required environment variable or exit with a clear error."""
    value = os.environ.get(key)
    if not value:
        print(f"::error::Missing required environment variable: {key}")
        sys.exit(1)
    return value


def call_deepseek(
    system_prompt: str,
    user_prompt: str,
) -> str:
    """
    Call DeepSeek Chat API with the given prompts.
    Returns the response text.
    
    Configuration via environment variables:
      - DEEPSEEK_API_KEY (required)
      - DEEPSEEK_API_URL (optional, default: https://api.deepseek.com/chat/completions)
      - DEEPSEEK_MODEL (optional, default: deepseek-chat)
      - DEEPSEEK_MAX_TOKENS (optional, default: 4096)
    """
    api_key = get_env_or_fail("DEEPSEEK_API_KEY")
    api_url = os.environ.get(
        "DEEPSEEK_API_URL",
        "https://api.deepseek.com/chat/completions"
    )
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    max_tokens = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "4096"))

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    })

    req = urllib.request.Request(
        api_url,
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            response_json = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"::error::DeepSeek API call failed with status {e.code}")
        # Be careful not to leak the full API key in logs — truncate if present
        safe_body = error_body.replace(api_key, "***")
        print(f"::debug::API response: {safe_body[:500]}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"::error::Network error calling DeepSeek API: {e.reason}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"::error::Invalid JSON response from DeepSeek API: {e}")
        sys.exit(1)

    try:
        return response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        print(f"::error::Unexpected API response structure: {e}")
        print(f"::debug::Response keys: {list(response_json.keys())}")
        sys.exit(1)


def load_diff(path: str = "/tmp/pr_diff.txt") -> str:
    """Load the diff from file, with size info."""
    if not os.path.exists(path):
        print(f"::error::Diff file not found at {path}")
        sys.exit(1)

    with open(path, "r") as f:
        content = f.read()

    if not content.strip():
        print("::warning::Diff is empty — nothing to review.")
        return ""

    size_kb = len(content) / 1024
    print(f"::debug::Loaded diff: {len(content)} bytes ({size_kb:.1f} KB)")
    return content


def write_review_output(text: str, path: str = "/tmp/review_output.txt"):
    """Write the review result to a file for downstream steps."""
    with open(path, "w") as f:
        f.write(text)
    print(f"::debug::Review output written to {path} ({len(text)} chars)")


def write_github_output(key: str, value: str):
    """Write to GITHUB_OUTPUT for sharing between steps."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{key}={value}\n")