#!/usr/bin/env python3
"""
Assignment Processor & Submitter
--------------------------------
Uses Anthropic's Claude Sonnet model to analyze .txt files in the current directory,
identifies which file contains the submission for 'shaliniscr@gmail.com',
and posts the submission entry to the TrainerCentral Assignments API.

API Target: https://trainer-central-assigments-api.onrender.com/api/entries
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

DEFAULT_API_BASE_URL = "https://trainer-central-assigments-api.onrender.com"
DEFAULT_TARGET_EMAIL = "shaliniscr@gmail.com"

# Model configuration: Map colloquial references like "sonnet 5.5" to claude-sonnet-5-5
MODEL_ALIASES = {
    "sonnet 5.5": "claude-sonnet-5-5",
    "sonnet-5.5": "claude-sonnet-5-5",
    "sonnet5.5": "claude-sonnet-5-5",
    "claude-sonnet-5-5": "claude-sonnet-5-5",
    "claude-sonnet-5.5": "claude-sonnet-5-5",
    "sonnet": "claude-sonnet-5-5",
}
DEFAULT_MODEL = "claude-sonnet-5-5"


def resolve_model_name(model_input: str) -> str:
    """Normalize and resolve model name, translating aliases like 'sonnet 5.5'."""
    normalized = model_input.strip().lower()
    return MODEL_ALIASES.get(normalized, model_input)


def find_txt_files(directory: Path) -> List[Path]:
    """Find all .txt files in the given directory."""
    return sorted(list(directory.glob("*.txt")))


def load_file_contents(file_paths: List[Path]) -> Dict[str, str]:
    """Read content of each file."""
    files_data = {}
    for p in file_paths:
        try:
            content = p.read_text(encoding="utf-8")
            files_data[p.name] = content
        except Exception as e:
            print(f"[WARN] Failed to read {p.name}: {e}", file=sys.stderr)
    return files_data


def analyze_files_with_anthropic(
    files_data: Dict[str, str],
    target_email: str,
    model_name: str,
    api_key: str,
) -> Dict[str, Any]:
    """
    Call Anthropic Messages API using Claude Sonnet to inspect all text files
    and determine which one contains the target email address, returning structured
    JSON for API submission.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    files_manifest = []
    for filename, content in files_data.items():
        files_manifest.append(f"=== File: {filename} ===\n{content}\n")

    combined_files = "\n".join(files_manifest)

    prompt = f"""You are an intelligent data analyst.
You have been provided with several text notification files from a learning management platform.
Your task is to analyze these files and find the file(s) that contain assignment submission details for the learner with email: '{target_email}'.

Here are the text files:
{combined_files}

Instructions:
1. Examine each file carefully.
2. Determine which file(s) contain the target email: '{target_email}'.
3. For each matching file, extract:
   - "filename": Name of the file.
   - "sender": The learner name or username identifier (e.g., 'shaliniscr' or 'shaliniscr@gmail.com', max 100 characters).
   - "text": The full text content of the submission file (max 10000 characters) to be posted to the /api/entries dashboard.
   - "explanation": Brief explanation of the match.

Respond ONLY with valid JSON in the following format (no markdown code fence, or standard ```json block):
{{
  "analysis_summary": "Brief summary of files inspected and outcome",
  "matches": [
    {{
      "filename": "<filename>",
      "sender": "<sender_id>",
      "text": "<text_to_post>",
      "explanation": "<reason>"
    }}
  ]
}}
"""

    print(f"[INFO] Invoking Anthropic API (model: {model_name})...")
    response = client.messages.create(
        model=model_name,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()

    # Extract JSON if wrapped in markdown code blocks
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
    if json_match:
        raw_text = json_match.group(1).strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as err:
        print(f"[ERROR] Failed to parse JSON from Anthropic response: {err}", file=sys.stderr)
        print(f"[DEBUG] Raw response:\n{raw_text}", file=sys.stderr)
        raise


def fallback_local_analysis(files_data: Dict[str, str], target_email: str) -> Dict[str, Any]:
    """Fallback in case no Anthropic API key is provided or offline mode is requested."""
    matches = []
    for filename, content in files_data.items():
        if target_email.lower() in content.lower():
            # Extract username prefix from email if possible
            sender = target_email.split("@")[0]
            matches.append({
                "filename": filename,
                "sender": sender,
                "text": content,
                "explanation": f"Found '{target_email}' directly in file content."
            })
    return {
        "analysis_summary": f"Local rule-based scan for '{target_email}' across {len(files_data)} files.",
        "matches": matches,
    }


def post_entry_to_api(
    base_url: str,
    text: str,
    sender: str,
    x_api_key: Optional[str] = None,
) -> requests.Response:
    """Post submission entry to /api/entries."""
    endpoint = f"{base_url.rstrip('/')}/api/entries"
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    if x_api_key:
        headers["x-api-key"] = x_api_key

    payload = {
        "text": text,
        "sender": sender,
    }

    response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    return response


def main():
    parser = argparse.ArgumentParser(
        description="Analyze assignment submission text files with Anthropic Claude Sonnet and post to API."
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="Directory containing .txt files (default: current directory)",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=DEFAULT_TARGET_EMAIL,
        help=f"Target email to search for (default: {DEFAULT_TARGET_EMAIL})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sonnet 5.5",
        help="Anthropic model name or alias (default: 'sonnet 5.5' -> claude-sonnet-5-5)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=DEFAULT_API_BASE_URL,
        help=f"Base URL of TrainerCentral Assignments API (default: {DEFAULT_API_BASE_URL})",
    )
    parser.add_argument(
        "--anthropic-api-key",
        type=str,
        default=None,
        help="Anthropic API Key (defaults to ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--x-api-key",
        type=str,
        default=os.environ.get("TRAINER_CENTRAL_API_KEY"),
        help="Optional X-Api-Key for TrainerCentral API",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze files without posting to the TrainerCentral API",
    )
    parser.add_argument(
        "--fallback-local",
        action="store_true",
        help="Perform local text matching if ANTHROPIC_API_KEY is not configured",
    )

    args = parser.parse_args()

    work_dir = Path(args.dir).resolve()
    print(f"=== TrainerCentral Assignment Analysis ===")
    print(f"Scanning directory: {work_dir}")
    print(f"Target email:       {args.email}")

    txt_files = find_txt_files(work_dir)
    if not txt_files:
        print(f"[ERROR] No .txt files found in {work_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(txt_files)} .txt file(s):")
    for f in txt_files:
        print(f"  - {f.name}")

    files_data = load_file_contents(txt_files)

    # Resolve Anthropic model name
    resolved_model = resolve_model_name(args.model)
    anthropic_key = args.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")

    analysis_result = None

    if anthropic_key:
        print(f"\n[1/2] Analyzing files using Anthropic Claude ({resolved_model})...")
        try:
            analysis_result = analyze_files_with_anthropic(
                files_data=files_data,
                target_email=args.email,
                model_name=resolved_model,
                api_key=anthropic_key,
            )
        except Exception as e:
            print(f"\n[ERROR] Anthropic API call failed: {e}", file=sys.stderr)
            if "authentication_error" in str(e).lower() or "401" in str(e):
                print(
                    "\n[TIP] The API key in .env or ANTHROPIC_API_KEY was rejected by Anthropic ('invalid x-api-key').\n"
                    "      Please check your key at https://console.anthropic.com/settings/keys.\n"
                    "      To run the script anyway using local search, add '--fallback-local':\n"
                    "      python3 process_assignments.py --fallback-local\n",
                    file=sys.stderr,
                )
            if args.fallback_local:
                print("[INFO] Falling back to local search...", file=sys.stderr)
                analysis_result = fallback_local_analysis(files_data, args.email)
            else:
                sys.exit(1)
    else:
        print("\n[WARN] ANTHROPIC_API_KEY is not set.")
        if args.fallback_local:
            print("[INFO] Proceeding with fallback local search as requested (--fallback-local)...")
            analysis_result = fallback_local_analysis(files_data, args.email)
        else:
            print("\nPlease provide an Anthropic API Key via:")
            print("  - Setting the ANTHROPIC_API_KEY environment variable (export ANTHROPIC_API_KEY=...)")
            print("  - Adding ANTHROPIC_API_KEY to a .env file")
            print("  - Passing --anthropic-api-key <key>")
            print("  - Or pass --fallback-local to test matching without the LLM.")
            sys.exit(1)

    print("\n--- Analysis Result ---")
    print(f"Summary: {analysis_result.get('analysis_summary', 'N/A')}")
    matches = analysis_result.get("matches", [])
    print(f"Matches found: {len(matches)}")

    if not matches:
        print(f"[INFO] No files containing '{args.email}' were identified.")
        sys.exit(0)

    for idx, match in enumerate(matches, 1):
        filename = match.get("filename")
        sender = match.get("sender")
        text = match.get("text")
        explanation = match.get("explanation", "")

        print(f"\nMatch #{idx}:")
        print(f"  File:        {filename}")
        print(f"  Sender:      {sender}")
        print(f"  Explanation: {explanation}")
        preview = text.replace('\n', ' ')[:100] if text else ""
        print(f"  Text preview:{preview}...")

        if args.dry_run:
            print("  [DRY-RUN] Skipping API call to TrainerCentral.")
            continue

        print(f"\n[2/2] Making API call to {args.api_url}/api/entries...")
        try:
            res = post_entry_to_api(
                base_url=args.api_url,
                text=text,
                sender=sender,
                x_api_key=args.x_api_key,
            )
            print(f"  Response Status: {res.status_code}")
            try:
                res_json = res.json()
                print(f"  Response Body:   {json.dumps(res_json, indent=2)}")
            except Exception:
                print(f"  Response Text:   {res.text}")

            if res.status_code in (200, 201):
                print(f"  [SUCCESS] Successfully posted entry for {sender} from {filename}!")
            else:
                print(f"  [ERROR] API request returned status {res.status_code}", file=sys.stderr)

        except Exception as exc:
            print(f"  [ERROR] Failed to post entry to API: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
