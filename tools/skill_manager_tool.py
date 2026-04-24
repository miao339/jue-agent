#!/usr/bin/env python3
"""
Skill Manager Tool -- Agent-Managed Skill Creation & Editing

Allows the agent to create, update, and delete skills, turning successful
approaches into reusable procedural knowledge. New skills are created in
~/.jue/skills/. Existing skills (bundled, hub-installed, or user-created)
can be modified or deleted wherever they live.

Skills are the agent's procedural memory: they capture *how to do a specific
type of task* based on proven experience. General memory (MEMORY.md, USER.md) is
broad and declarative. Skills are narrow and actionable.

Actions:
  create     -- Create a new skill (SKILL.md + directory structure)
  edit       -- Replace the SKILL.md content of a user skill (full rewrite)
  patch      -- Targeted find-and-replace within SKILL.md or any supporting file
  delete     -- Remove a user skill entirely
  write_file -- Add/overwrite a supporting file (reference, template, script, asset)
  remove_file-- Remove a supporting file from a user skill

Directory layout for user skills:
    ~/.jue/skills/
    ├── my-skill/
    │   ├── SKILL.md
    │   ├── references/
    │   ├── templates/
    │   ├── scripts/
    │   └── assets/
    └── category-name/
        └── another-skill/
            └── SKILL.md
"""

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from jue_constants import get_jue_home, display_jue_home
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Import security scanner — agent-created skills get the same scrutiny as
# community hub installs.
try:
    from tools.skills_guard import scan_skill, should_allow_install, format_scan_report
    _GUARD_AVAILABLE = True
except ImportError:
    _GUARD_AVAILABLE = False


def _security_scan_skill(skill_dir: Path) -> Optional[str]:
    """Scan a skill directory after write. Returns error string if blocked, else None."""
    if not _GUARD_AVAILABLE:
        return None
    try:
        result = scan_skill(skill_dir, source="agent-created")
        allowed, reason = should_allow_install(result)
        if allowed is False:
            report = format_scan_report(result)
            return f"Security scan blocked this skill ({reason}):\n{report}"
        if allowed is None:
            # "ask" verdict — for agent-created skills this means dangerous
            # findings were detected.  Block the skill and include the report.
            report = format_scan_report(result)
            logger.warning("Agent-created skill blocked (dangerous findings): %s", reason)
            return f"Security scan blocked this skill ({reason}):\n{report}"
    except Exception as e:
        logger.warning("Security scan failed for %s: %s", skill_dir, e, exc_info=True)
    return None

import yaml


# All skills live in ~/.jue/skills/ (single source of truth)
JUE_HOME = get_jue_home()
SKILLS_DIR = JUE_HOME / "skills"

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


def _is_local_skill(skill_path: Path) -> bool:
    """Check if a skill path is within the local SKILLS_DIR.

    Skills found in external_dirs are read-only from the agent's perspective.
    """
    try:
        skill_path.resolve().relative_to(SKILLS_DIR.resolve())
        return True
    except ValueError:
        return False
MAX_SKILL_CONTENT_CHARS = 100_000   # ~36k tokens at 2.75 chars/token
MAX_SKILL_FILE_BYTES = 1_048_576    # 1 MiB per supporting file

# Characters allowed in skill names (filesystem-safe, URL-friendly)
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')

# Subdirectories allowed for write_file/remove_file
ALLOWED_SUBDIRS = {"references", "templates", "scripts", "assets"}


# =============================================================================
# Validation helpers
# =============================================================================

def _validate_name(name: str) -> Optional[str]:
    """Validate a skill name. Returns error message or None if valid."""
    if not name:
        return "Skill name is required."
    if len(name) > MAX_NAME_LENGTH:
        return f"Skill name exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(name):
        return (
            f"Invalid skill name '{name}'. Use lowercase letters, numbers, "
            f"hyphens, dots, and underscores. Must start with a letter or digit."
        )
    return None


def _validate_category(category: Optional[str]) -> Optional[str]:
    """Validate an optional category name used as a single directory segment."""
    if category is None:
        return None
    if not isinstance(category, str):
        return "Category must be a string."

    category = category.strip()
    if not category:
        return None
    if "/" in category or "\\" in category:
        return (
            f"Invalid category '{category}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Categories must be a single directory name."
        )
    if len(category) > MAX_NAME_LENGTH:
        return f"Category exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(category):
        return (
            f"Invalid category '{category}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Categories must be a single directory name."
        )
    return None


def _validate_frontmatter(content: str) -> Optional[str]:
    """
    Validate that SKILL.md content has proper frontmatter with required fields.
    Returns error message or None if valid.
    """
    if not content.strip():
        return "Content cannot be empty."

    if not content.startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---). See existing skills for format."

    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return "SKILL.md frontmatter is not closed. Ensure you have a closing '---' line."

    yaml_content = content[3:end_match.start() + 3]

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return f"YAML frontmatter parse error: {e}"

    if not isinstance(parsed, dict):
        return "Frontmatter must be a YAML mapping (key: value pairs)."

    if "name" not in parsed:
        return "Frontmatter must include 'name' field."
    if "description" not in parsed:
        return "Frontmatter must include 'description' field."
    if len(str(parsed["description"])) > MAX_DESCRIPTION_LENGTH:
        return f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters."

    body = content[end_match.end() + 3:].strip()
    if not body:
        return "SKILL.md must have content after the frontmatter (instructions, procedures, etc.)."

    return None


def _validate_content_size(content: str, label: str = "SKILL.md") -> Optional[str]:
    """Check that content doesn't exceed the character limit for agent writes.

    Returns an error message or None if within bounds.
    """
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        return (
            f"{label} content is {len(content):,} characters "
            f"(limit: {MAX_SKILL_CONTENT_CHARS:,}). "
            f"Consider splitting into a smaller SKILL.md with supporting files "
            f"in references/ or templates/."
        )
    return None


def _resolve_skill_dir(name: str, category: str = None) -> Path:
    """Build the directory path for a new skill, optionally under a category."""
    if category:
        return SKILLS_DIR / category / name
    return SKILLS_DIR / name


def _find_skill(name: str) -> Optional[Dict[str, Any]]:
    """
    Find a skill by name across all skill directories.

    Searches the local skills dir (~/.jue/skills/) first, then any
    external dirs configured via skills.external_dirs.  Returns
    {"path": Path} or None.
    """
    from agent.skill_utils import get_all_skills_dirs
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            if skill_md.parent.name == name:
                return {"path": skill_md.parent}
    return None


def _validate_file_path(file_path: str) -> Optional[str]:
    """
    Validate a file path for write_file/remove_file.
    Must be under an allowed subdirectory and not escape the skill dir.
    """
    from tools.path_security import has_traversal_component

    if not file_path:
        return "file_path is required."

    normalized = Path(file_path)

    # Prevent path traversal
    if has_traversal_component(file_path):
        return "Path traversal ('..') is not allowed."

    # Must be under an allowed subdirectory
    if not normalized.parts or normalized.parts[0] not in ALLOWED_SUBDIRS:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS))
        return f"File must be under one of: {allowed}. Got: '{file_path}'"

    # Must have a filename (not just a directory)
    if len(normalized.parts) < 2:
        return f"Provide a file path, not just a directory. Example: '{normalized.parts[0]}/myfile.md'"

    return None


def _resolve_skill_target(skill_dir: Path, file_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a supporting-file path and ensure it stays within the skill directory."""
    from tools.path_security import validate_within_dir

    target = skill_dir / file_path
    error = validate_within_dir(target, skill_dir)
    if error:
        return None, error
    return target, None


def _atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Atomically write text content to a file.
    
    Uses a temporary file in the same directory and os.replace() to ensure
    the target file is never left in a partially-written state if the process
    crashes or is interrupted.
    
    Args:
        file_path: Target file path
        content: Content to write
        encoding: Text encoding (default: utf-8)
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.tmp.",
        suffix="",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(temp_path, file_path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            logger.error("Failed to remove temporary file %s during atomic write", temp_path, exc_info=True)
        raise


# =============================================================================
# Core actions
# =============================================================================

def _create_skill(name: str, content: str, category: str = None) -> Dict[str, Any]:
    """Create a new user skill with SKILL.md content."""
    # Validate name
    err = _validate_name(name)
    if err:
        return {"success": False, "error": err}

    err = _validate_category(category)
    if err:
        return {"success": False, "error": err}

    # Validate content
    err = _validate_frontmatter(content)
    if err:
        return {"success": False, "error": err}

    err = _validate_content_size(content)
    if err:
        return {"success": False, "error": err}

    # Check for name collisions across all directories
    existing = _find_skill(name)
    if existing:
        return {
            "success": False,
            "error": f"A skill named '{name}' already exists at {existing['path']}."
        }

    # Create the skill directory
    skill_dir = _resolve_skill_dir(name, category)
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Write SKILL.md atomically
    skill_md = skill_dir / "SKILL.md"
    _atomic_write_text(skill_md, content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        shutil.rmtree(skill_dir, ignore_errors=True)
        return {"success": False, "error": scan_error}

    result = {
        "success": True,
        "message": f"Skill '{name}' created.",
        "path": str(skill_dir.relative_to(SKILLS_DIR)),
        "skill_md": str(skill_md),
    }
    if category:
        result["category"] = category
    result["hint"] = (
        "To add reference files, templates, or scripts, use "
        "skill_manage(action='write_file', name='{}', file_path='references/example.md', file_content='...')".format(name)
    )
    return result


def _edit_skill(name: str, content: str) -> Dict[str, Any]:
    """Replace the SKILL.md of any existing skill (full rewrite)."""
    err = _validate_frontmatter(content)
    if err:
        return {"success": False, "error": err}

    err = _validate_content_size(content)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": f"Skill '{name}' not found. Use skills_list() to see available skills."}

    if not _is_local_skill(existing["path"]):
        return {"success": False, "error": f"Skill '{name}' is in an external directory and cannot be modified. Copy it to your local skills directory first."}

    skill_md = existing["path"] / "SKILL.md"
    # Back up original content for rollback
    original_content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else None
    _atomic_write_text(skill_md, content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(existing["path"])
    if scan_error:
        if original_content is not None:
            _atomic_write_text(skill_md, original_content)
        return {"success": False, "error": scan_error}

    return {
        "success": True,
        "message": f"Skill '{name}' updated.",
        "path": str(existing["path"]),
    }


def _patch_skill(
    name: str,
    old_string: str,
    new_string: str,
    file_path: str = None,
    replace_all: bool = False,
) -> Dict[str, Any]:
    """Targeted find-and-replace within a skill file.

    Defaults to SKILL.md. Use file_path to patch a supporting file instead.
    Requires a unique match unless replace_all is True.
    """
    if not old_string:
        return {"success": False, "error": "old_string is required for 'patch'."}
    if new_string is None:
        return {"success": False, "error": "new_string is required for 'patch'. Use an empty string to delete matched text."}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": f"Skill '{name}' not found."}

    if not _is_local_skill(existing["path"]):
        return {"success": False, "error": f"Skill '{name}' is in an external directory and cannot be modified. Copy it to your local skills directory first."}

    skill_dir = existing["path"]

    if file_path:
        # Patching a supporting file
        err = _validate_file_path(file_path)
        if err:
            return {"success": False, "error": err}
        target, err = _resolve_skill_target(skill_dir, file_path)
        if err:
            return {"success": False, "error": err}
    else:
        # Patching SKILL.md
        target = skill_dir / "SKILL.md"

    if not target.exists():
        return {"success": False, "error": f"File not found: {target.relative_to(skill_dir)}"}

    content = target.read_text(encoding="utf-8")

    # Use the same fuzzy matching engine as the file patch tool.
    # This handles whitespace normalization, indentation differences,
    # escape sequences, and block-anchor matching — saving the agent
    # from exact-match failures on minor formatting mismatches.
    from tools.fuzzy_match import fuzzy_find_and_replace

    new_content, match_count, _strategy, match_error = fuzzy_find_and_replace(
        content, old_string, new_string, replace_all
    )
    if match_error:
        # Show a short preview of the file so the model can self-correct
        preview = content[:500] + ("..." if len(content) > 500 else "")
        err_msg = match_error
        try:
            from tools.fuzzy_match import format_no_match_hint
            err_msg += format_no_match_hint(match_error, match_count, old_string, content)
        except Exception:
            pass
        return {
            "success": False,
            "error": err_msg,
            "file_preview": preview,
        }

    # Check size limit on the result
    target_label = "SKILL.md" if not file_path else file_path
    err = _validate_content_size(new_content, label=target_label)
    if err:
        return {"success": False, "error": err}

    # If patching SKILL.md, validate frontmatter is still intact
    if not file_path:
        err = _validate_frontmatter(new_content)
        if err:
            return {
                "success": False,
                "error": f"Patch would break SKILL.md structure: {err}",
            }

    original_content = content  # for rollback
    _atomic_write_text(target, new_content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        _atomic_write_text(target, original_content)
        return {"success": False, "error": scan_error}

    return {
        "success": True,
        "message": f"Patched {'SKILL.md' if not file_path else file_path} in skill '{name}' ({match_count} replacement{'s' if match_count > 1 else ''}).",
    }


def _delete_skill(name: str) -> Dict[str, Any]:
    """Delete a skill."""
    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": f"Skill '{name}' not found."}

    if not _is_local_skill(existing["path"]):
        return {"success": False, "error": f"Skill '{name}' is in an external directory and cannot be deleted."}

    skill_dir = existing["path"]
    shutil.rmtree(skill_dir)

    # Clean up empty category directories (don't remove SKILLS_DIR itself)
    parent = skill_dir.parent
    if parent != SKILLS_DIR and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()

    return {
        "success": True,
        "message": f"Skill '{name}' deleted.",
    }


def _write_file(name: str, file_path: str, file_content: str) -> Dict[str, Any]:
    """Add or overwrite a supporting file within any skill directory."""
    err = _validate_file_path(file_path)
    if err:
        return {"success": False, "error": err}

    if not file_content and file_content != "":
        return {"success": False, "error": "file_content is required."}

    # Check size limits
    content_bytes = len(file_content.encode("utf-8"))
    if content_bytes > MAX_SKILL_FILE_BYTES:
        return {
            "success": False,
            "error": (
                f"File content is {content_bytes:,} bytes "
                f"(limit: {MAX_SKILL_FILE_BYTES:,} bytes / 1 MiB). "
                f"Consider splitting into smaller files."
            ),
        }
    err = _validate_content_size(file_content, label=file_path)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": f"Skill '{name}' not found. Create it first with action='create'."}

    if not _is_local_skill(existing["path"]):
        return {"success": False, "error": f"Skill '{name}' is in an external directory and cannot be modified. Copy it to your local skills directory first."}

    target, err = _resolve_skill_target(existing["path"], file_path)
    if err:
        return {"success": False, "error": err}
    target.parent.mkdir(parents=True, exist_ok=True)
    # Back up for rollback
    original_content = target.read_text(encoding="utf-8") if target.exists() else None
    _atomic_write_text(target, file_content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(existing["path"])
    if scan_error:
        if original_content is not None:
            _atomic_write_text(target, original_content)
        else:
            target.unlink(missing_ok=True)
        return {"success": False, "error": scan_error}

    return {
        "success": True,
        "message": f"File '{file_path}' written to skill '{name}'.",
        "path": str(target),
    }


def _remove_file(name: str, file_path: str) -> Dict[str, Any]:
    """Remove a supporting file from any skill directory."""
    err = _validate_file_path(file_path)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": f"Skill '{name}' not found."}

    if not _is_local_skill(existing["path"]):
        return {"success": False, "error": f"Skill '{name}' is in an external directory and cannot be modified."}

    skill_dir = existing["path"]

    target, err = _resolve_skill_target(skill_dir, file_path)
    if err:
        return {"success": False, "error": err}
    if not target.exists():
        # List what's actually there for the model to see
        available = []
        for subdir in ALLOWED_SUBDIRS:
            d = skill_dir / subdir
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file():
                        available.append(str(f.relative_to(skill_dir)))
        return {
            "success": False,
            "error": f"File '{file_path}' not found in skill '{name}'.",
            "available_files": available if available else None,
        }

    target.unlink()

    # Clean up empty subdirectories
    parent = target.parent
    if parent != skill_dir and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()

    return {
        "success": True,
        "message": f"File '{file_path}' removed from skill '{name}'.",
    }


def _record_triplet(name: str, content: str | None, task_id: str = "", session_id: str = "") -> Dict[str, Any]:
    """Record a judgment triplet into Harness③.

    name: used as a short label/tag for the triplet
    content: JSON string with fields: situation, judgment, structure, track, tags
    task_id: current task ID (auto-filled from agent context if available)
    session_id: current session ID (auto-filled from agent context if available)
    """
    if not content:
        return {"success": False, "error": "content is required for 'record_triplet'. Provide situation, judgment, and structure."}

    try:
        from jue.harness3.store import JudgmentTriplet, TripletMetaCheck, TripletStore
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available. Cannot record triplet."}

    # Parse content — can be JSON or plain text with sections
    try:
        fields = json.loads(content)
    except json.JSONDecodeError:
        # Try parsing as structured text: "situation: ... judgment: ... structure: ..."
        fields = _parse_triplet_text(content)

    if not fields.get("situation") or not fields.get("judgment") or not fields.get("structure"):
        return {
            "success": False,
            "error": "Triplet requires all three fields: situation (what you encountered), judgment (why you decided), structure (what direction this points to). Missing one degrades to skill-only accumulation.",
        }

    # Build tags: merge explicit tags from content with name-based tag
    explicit_tags = fields.get("tags", [])
    name_tag = name.strip().lower().replace(" ", "-") if name and name not in explicit_tags else None
    final_tags = list(explicit_tags)
    if name_tag:
        final_tags.append(name_tag)

    # Resolve task_id / session_id: prefer explicit args, then try agent context
    resolved_task_id = task_id
    resolved_session_id = session_id
    if not resolved_task_id or not resolved_session_id:
        try:
            import run_agent as _ra
            # Walk the call stack to find the AIAgent instance
            import inspect
            for frame_info in inspect.stack():
                frame_locals = frame_info[0].f_locals
                agent = frame_locals.get("self")
                if isinstance(agent, _ra.AIAgent):
                    if not resolved_task_id:
                        resolved_task_id = getattr(agent, "_current_task_id", "") or ""
                    if not resolved_session_id:
                        resolved_session_id = getattr(agent, "session_id", "") or ""
                    break
        except Exception:
            pass

    triplet = JudgmentTriplet(
        situation=fields["situation"],
        judgment=fields["judgment"],
        structure=fields["structure"],
        tags=final_tags,
        track=fields.get("track", "harness"),
        task_id=resolved_task_id,
        session_id=resolved_session_id,
    )

    # Meta-check: ask the model's self-assessment
    meta_answer = fields.get("meta_check_answer", "")
    meta_passed = True
    if meta_answer:
        # If model explicitly says this is "规定动作" rather than "指出方向", flag it
        if any(kw in meta_answer.lower() for kw in ["规定动作", "rule", "prescribe", "if-then", "步骤"]):
            meta_passed = False

    meta_check = TripletMetaCheck(
        passed=meta_passed,
        answer=meta_answer,
    )

    store = TripletStore()
    triplet_id = store.write(triplet, meta_check)

    if not triplet_id:
        return {"success": False, "error": "Triplet write failed. Check that all three fields are non-empty."}

    return {
        "success": True,
        "message": f"Judgment triplet recorded: {triplet_id} (track={triplet.track})",
        "triplet_id": triplet_id,
        "meta_check_passed": meta_passed,
        "meta_check_question": meta_check.question,
    }


def _flag_triplet(name: str, content: str | None) -> Dict[str, Any]:
    """Flag a triplet as potentially problematic (status -> flagged).

    name: triplet_id to flag
    content: optional reason for flagging
    """
    triplet_id = name.strip()
    if not triplet_id:
        return {"success": False, "error": "triplet_id (name field) is required for 'flag_triplet'."}

    try:
        from jue.harness3.store import TripletStore
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available."}

    store = TripletStore()
    ok = store.update_status(triplet_id, "flagged")
    if not ok:
        return {"success": False, "error": f"Could not flag triplet '{triplet_id}'. Not found or invalid."}

    reason = content.strip() if content else ""
    return {
        "success": True,
        "message": f"Triplet {triplet_id} flagged.",
        "triplet_id": triplet_id,
        "new_status": "flagged",
        "reason": reason,
    }


def _revoke_triplet(name: str, content: str | None) -> Dict[str, Any]:
    """Revoke a triplet entirely (status -> revoked).

    name: triplet_id to revoke
    content: optional reason for revocation
    """
    triplet_id = name.strip()
    if not triplet_id:
        return {"success": False, "error": "triplet_id (name field) is required for 'revoke_triplet'."}

    try:
        from jue.harness3.store import TripletStore
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available."}

    store = TripletStore()
    ok = store.update_status(triplet_id, "revoked")
    if not ok:
        return {"success": False, "error": f"Could not revoke triplet '{triplet_id}'. Not found or invalid."}

    reason = content.strip() if content else ""
    return {
        "success": True,
        "message": f"Triplet {triplet_id} revoked.",
        "triplet_id": triplet_id,
        "new_status": "revoked",
        "reason": reason,
    }


def _parse_triplet_text(text: str) -> dict:
    """Parse structured text into triplet fields.

    Accepts formats like:
    situation: ...
    judgment: ...
    structure: ...
    """
    fields = {}
    patterns = {
        "name": r"name\s*[:：]\s*(.+?)(?=category|situation|judgment|structure|$)",
        "category": r"category\s*[:：]\s*(.+?)(?=name|situation|judgment|structure|$)",
        "situation": r"situation\s*[:：]\s*(.+?)(?=name|category|judgment|structure|$)",
        "judgment": r"judgment\s*[:：]\s*(.+?)(?=name|category|situation|structure|$)",
        "structure": r"structure\s*[:：]\s*(.+?)(?=name|category|situation|judgment|$)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            fields[key] = match.group(1).strip()
    return fields


# =============================================================================
# Harness action handlers (generate, evolve, list, use)
# =============================================================================

def _generate_harness(name: str, content: str | None, category: str | None = None) -> Dict[str, Any]:
    """Generate a harness record from current judgment context.

    name: human-readable harness title
    category: human-readable harness category
    content: JSON string with fields:
        situation, judgment, structure,
        root_paradigm_fragment (optional, can only narrow main paradigm),
        soul (optional, can differ from main SOUL),
        api_config_name (optional, references config.json entry),
        tags (optional list),
        evolution_direction (optional, describes when this harness might need to evolve)
    """
    if not content:
        return {"success": False, "error": "content is required for 'generate_harness'. Provide situation, judgment, and structure."}

    try:
        from jue.harness3.store import HarnessRecord, HarnessStore
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available."}

    try:
        fields = json.loads(content)
    except json.JSONDecodeError:
        fields = _parse_triplet_text(content)

    human_name = str(fields.get("name") or name or "").strip()
    human_category = str(fields.get("category") or category or "").strip()

    if not human_name or not human_category:
        return {"success": False, "error": "Harness requires name and category. Both are non-optional."}

    if not fields.get("situation") or not fields.get("judgment") or not fields.get("structure"):
        return {"success": False, "error": "Harness requires situation, judgment, and structure. All three are non-optional."}

    # Build tags: merge explicit tags with name-based tag
    explicit_tags = fields.get("tags", [])
    name_tag = human_name.lower().replace(" ", "-") if human_name and human_name not in explicit_tags else None
    final_tags = list(explicit_tags)
    if name_tag:
        final_tags.append(name_tag)
    if human_category not in final_tags:
        final_tags.append(human_category)

    record = HarnessRecord(
        name=human_name,
        category=human_category,
        situation=fields["situation"],
        judgment=fields["judgment"],
        structure=fields["structure"],
        root_paradigm_fragment=fields.get("root_paradigm_fragment", ""),
        soul=fields.get("soul", ""),
        api_config_name=fields.get("api_config_name", ""),
        tags=final_tags,
        track="harness",
        evolution_direction=fields.get("evolution_direction", ""),
    )

    store = HarnessStore()
    harness_id = store.write(record)

    if not harness_id:
        return {"success": False, "error": "Harness write failed. Check that all three core fields are non-empty."}

    return {
        "success": True,
        "message": f"Harness generated: {harness_id}",
        "harness_id": harness_id,
        "name": human_name,
        "category": human_category,
        "version": 1,
    }


def _evolve_harness(name: str, content: str | None) -> Dict[str, Any]:
    """Evolve an existing harness to a new version.

    name: harness_id of the harness to evolve
    content: JSON string with updated fields + evolution_reason + evolution_direction (optional)
    """
    if not name:
        return {"success": False, "error": "name (harness_id) is required for 'evolve_harness'."}
    if not content:
        return {"success": False, "error": "content is required for 'evolve_harness'. Provide updated fields and evolution_reason."}

    try:
        from jue.harness3.store import HarnessRecord, HarnessStore
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available."}

    try:
        fields = json.loads(content)
    except json.JSONDecodeError:
        fields = _parse_triplet_text(content)

    reason = fields.get("evolution_reason", fields.get("reason", ""))

    store = HarnessStore()
    old = store.get(name)
    if not old:
        return {"success": False, "error": f"Harness '{name}' not found. Cannot evolve non-existent harness."}

    # Build updated record from old + new fields
    updated = HarnessRecord(
        name=fields.get("name", old.name),
        category=fields.get("category", old.category),
        situation=fields.get("situation", old.situation),
        judgment=fields.get("judgment", old.judgment),
        structure=fields.get("structure", old.structure),
        root_paradigm_fragment=fields.get("root_paradigm_fragment", old.root_paradigm_fragment),
        soul=fields.get("soul", old.soul),
        api_config_name=fields.get("api_config_name", old.api_config_name),
        tags=fields.get("tags", old.tags),
        track="harness",
        evolution_direction=fields.get("evolution_direction", old.evolution_direction),
    )

    new_id = store.evolve(name, updated, reason=reason)
    if not new_id:
        return {"success": False, "error": "Harness evolution failed."}

    new_rec = store.get(new_id)
    return {
        "success": True,
        "message": f"Harness evolved: {new_id} → v{new_rec.version}",
        "harness_id": new_id,
        "name": new_rec.name,
        "category": new_rec.category,
        "version": new_rec.version,
        "evolution_reason": reason,
    }


def _list_harnesses(name: str, content: str | None) -> Dict[str, Any]:
    """List harness records, optionally filtered by tags.

    name: unused (kept for API consistency)
    content: optional JSON with 'tags' (list) and 'limit' (int)
    """
    try:
        from jue.harness3.store import HarnessStore
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available."}

    tags = None
    limit = 20
    if content:
        try:
            fields = json.loads(content)
            tags = fields.get("tags")
            limit = fields.get("limit", 20)
        except json.JSONDecodeError:
            pass

    store = HarnessStore()
    results = store.list_harnesses(tags=tags, limit=limit)

    return {
        "success": True,
        "count": len(results),
        "harnesses": results,
    }


def _use_harness(name: str, content: str | None) -> Dict[str, Any]:
    """Load a harness for injection into the current context.

    name: harness_id to load
    content: unused

    Returns the full harness record including root_paradigm_fragment and soul
    for orientation.py to inject.
    """
    if not name:
        return {"success": False, "error": "name (harness_id) is required for 'use_harness'."}

    try:
        from jue.harness3.store import HarnessStore
        from jue.harness3.harness_config import resolve_api
    except ImportError:
        return {"success": False, "error": "Jue harness3 module not available."}

    store = HarnessStore()
    record = store.get(name)
    if not record:
        return {"success": False, "error": f"Harness '{name}' not found."}

    # Resolve API config for this harness
    api = resolve_api(record.api_config_name)

    return {
        "success": True,
        "harness_id": record.harness_id,
        "name": record.name,
        "category": record.category,
        "version": record.version,
        "situation": record.situation,
        "judgment": record.judgment,
        "structure": record.structure,
        "root_paradigm_fragment": record.root_paradigm_fragment,
        "soul": record.soul,
        "api_config_name": record.api_config_name,
        "api_resolved": {
            "provider": api.provider,
            "base_url": api.base_url,
            "api_mode": api.api_mode,
            "model_id": api.model_id,
            "credential_pool_name": api.credential_pool_name,
            "fallbacks": len(api.fallback_providers),
            # api_key intentionally NOT returned to model
        },
        "tags": record.tags,
    }


# =============================================================================
# Main entry point
# =============================================================================

def skill_manage(
    action: str,
    name: str,
    content: str = None,
    category: str = None,
    file_path: str = None,
    file_content: str = None,
    old_string: str = None,
    new_string: str = None,
    replace_all: bool = False,
    task_id: str = "",
    session_id: str = "",
) -> str:
    """
    Manage user-created skills. Dispatches to the appropriate action handler.

    Returns JSON string with results.
    """
    if action == "create":
        if not content:
            return tool_error("content is required for 'create'. Provide the full SKILL.md text (frontmatter + body).", success=False)
        result = _create_skill(name, content, category)

    elif action == "edit":
        if not content:
            return tool_error("content is required for 'edit'. Provide the full updated SKILL.md text.", success=False)
        result = _edit_skill(name, content)

    elif action == "patch":
        if not old_string:
            return tool_error("old_string is required for 'patch'. Provide the text to find.", success=False)
        if new_string is None:
            return tool_error("new_string is required for 'patch'. Use empty string to delete matched text.", success=False)
        result = _patch_skill(name, old_string, new_string, file_path, replace_all)

    elif action == "delete":
        result = _delete_skill(name)

    elif action == "write_file":
        if not file_path:
            return tool_error("file_path is required for 'write_file'. Example: 'references/api-guide.md'", success=False)
        if file_content is None:
            return tool_error("file_content is required for 'write_file'.", success=False)
        result = _write_file(name, file_path, file_content)

    elif action == "remove_file":
        if not file_path:
            return tool_error("file_path is required for 'remove_file'.", success=False)
        result = _remove_file(name, file_path)

    elif action == "record_triplet":
        result = _record_triplet(name, content, task_id=task_id, session_id=session_id)

    elif action == "flag_triplet":
        result = _flag_triplet(name, content)

    elif action == "revoke_triplet":
        result = _revoke_triplet(name, content)

    elif action == "generate_harness":
        result = _generate_harness(name, content, category=category)

    elif action == "evolve_harness":
        result = _evolve_harness(name, content)

    elif action == "list_harnesses":
        result = _list_harnesses(name, content)

    elif action == "use_harness":
        result = _use_harness(name, content)

    else:
        result = {"success": False, "error": f"Unknown action '{action}'. Use: create, edit, patch, delete, write_file, remove_file, record_triplet, generate_harness, evolve_harness, list_harnesses, use_harness"}

    if result.get("success"):
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)
        except Exception:
            pass

        # Jue: use_harness成功时，把harness_id存到agent实例上，让下次prompt构建时注入
        if action == "use_harness" and result.get("harness_id"):
            try:
                import run_agent as _ra
                from jue.harness3.harness_config import resolve_api
                import inspect
                for frame_info in inspect.stack():
                    frame_locals = frame_info[0].f_locals
                    agent = frame_locals.get("self")
                    if isinstance(agent, _ra.AIAgent):
                        agent._active_harness_id = result["harness_id"]
                        agent._active_harness_api_config_name = result.get("api_config_name", "") or ""
                        api_cfg = resolve_api(result.get("api_config_name", "") or "")
                        if hasattr(agent, "apply_harness_runtime_config"):
                            agent.apply_harness_runtime_config(api_cfg)
                        # 清system prompt缓存，下次turn会重建
                        if hasattr(agent, '_cached_system_prompt'):
                            agent._cached_system_prompt = None
                        break
            except Exception:
                pass

    return json.dumps(result, ensure_ascii=False)


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

SKILL_MANAGE_SCHEMA = {
    "name": "skill_manage",
    "description": (
        "Manage skills and judgment triplets. Jue has two tracks of accumulation:\n"
        "- Skills: reusable approaches for recurring task types (做法)\n"
        "- Harness triplets: judgment records — situation + judgment process + generated structure (为什么这么做)\n\n"
        f"Skills go to {display_jue_home()}/skills/; triplets go to {display_jue_home()}/harness3/\n\n"
        "Actions: create, patch, edit, delete, write_file, remove_file, record_triplet, generate_harness, evolve_harness, list_harnesses, use_harness\n\n"
        "Create skill when: you discover a reusable procedure worth remembering.\n"
        "Record triplet when: you made a judgment worth accumulating — "
        "the situation, why you judged as you did, and what direction it points to.\n"
        "Do NOT wait for a tool-call count threshold. Only record when you genuinely "
        "judge that this experience contains something worth carrying forward.\n\n"
        "Triplet format (for record_triplet):\\n"
        "  situation: what you encountered (specific, not abstract)\\n"
        "  judgment: why you decided as you did (not what you did)\\n"
        "  structure: what direction this points to (not what action to take)\\n"
        "  tags: list of short labels for retrieval (e.g. ['deletion', 'intent-gap'])\\n"
        "  track: 'harness' for judgment accumulation, 'skill' for capability accumulation\\n\\n"
        "Update when: instructions stale/wrong, OS-specific failures, "
        "missing steps or pitfalls found during use. "
        "If you used a skill and hit issues not covered by it, patch it immediately.\n\n"
        "After difficult/iterative tasks, offer to save as a skill. "
        "Skip for simple one-offs. Confirm with user before creating/deleting.\n\n"
        "Good skills: trigger conditions, numbered steps with exact commands, "
        "pitfalls section, verification steps. Use skill_view() to see format examples."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "patch", "edit", "delete", "write_file", "remove_file", "record_triplet", "flag_triplet", "revoke_triplet", "generate_harness", "evolve_harness", "list_harnesses", "use_harness"],
                "description": "The action to perform. 'record_triplet' writes a judgment triplet. 'flag_triplet' flags a triplet as potentially problematic. 'revoke_triplet' revokes a triplet entirely. 'generate_harness' creates a harness record. 'evolve_harness' evolves an existing harness to a new version. 'list_harnesses' lists harness records. 'use_harness' loads a harness for injection."
            },
            "name": {
                "type": "string",
                "description": (
                    "Skill name (lowercase, hyphens/underscores, max 64 chars). "
                    "For 'generate_harness', this is the required human-readable harness title. "
                    "Must match an existing skill for patch/edit/delete/write_file/remove_file."
                )
            },
            "content": {
                "type": "string",
                "description": (
                    "Full SKILL.md content (YAML frontmatter + markdown body). "
                    "Required for 'create' and 'edit'. For 'edit', read the skill "
                    "first with skill_view() and provide the complete updated text. "
                    "For 'generate_harness', provide JSON or labeled text with situation, "
                    "judgment, and structure; optional root_paradigm_fragment, soul, "
                    "api_config_name, tags, and evolution_direction."
                )
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Text to find in the file (required for 'patch'). Must be unique "
                    "unless replace_all=true. Include enough surrounding context to "
                    "ensure uniqueness."
                )
            },
            "new_string": {
                "type": "string",
                "description": (
                    "Replacement text (required for 'patch'). Can be empty string "
                    "to delete the matched text."
                )
            },
            "replace_all": {
                "type": "boolean",
                "description": "For 'patch': replace all occurrences instead of requiring a unique match (default: false)."
            },
            "category": {
                "type": "string",
                "description": (
                    "For 'create', optional category/domain for organizing the skill "
                    "(e.g., 'devops', 'data-science', 'mlops'). Creates a subdirectory grouping. "
                    "For 'generate_harness', this is the required human-readable harness category "
                    "(e.g., '对话判断', '代码操作')."
                )
            },
            "file_path": {
                "type": "string",
                "description": (
                    "Path to a supporting file within the skill directory. "
                    "For 'write_file'/'remove_file': required, must be under references/, "
                    "templates/, scripts/, or assets/. "
                    "For 'patch': optional, defaults to SKILL.md if omitted."
                )
            },
            "file_content": {
                "type": "string",
                "description": "Content for the file. Required for 'write_file'."
            },
        },
        "required": ["action", "name"],
    },
}


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="skill_manage",
    toolset="skills",
    schema=SKILL_MANAGE_SCHEMA,
    handler=lambda args, **kw: skill_manage(
        action=args.get("action", ""),
        name=args.get("name", ""),
        content=args.get("content"),
        category=args.get("category"),
        file_path=args.get("file_path"),
        file_content=args.get("file_content"),
        old_string=args.get("old_string"),
        new_string=args.get("new_string"),
        replace_all=args.get("replace_all", False),
        task_id=kw.get("task_id", ""),
        session_id=kw.get("session_id", "")),
    emoji="📝",
)
