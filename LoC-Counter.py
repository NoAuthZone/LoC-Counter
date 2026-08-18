#!/usr/bin/env python3
"""

--- LoC-Counter --- 

Standalone lines-of-code (LoC) counter.
	Version   : 1.0
	Author    : NoAuthZone
	GitHub    : https://github.com/NoAuthZone/LoC-Counter

"""

import argparse
import os
import re
import sys

PROGRAM_NAME = "LoC Counter"
PROGRAM_VERSION = "1.0"
PROGRAM_SOURCE = "Derived from NoAuthZone/CommentRemover (CommentRemoverV2_2.py)"

LOC_CATEGORIES = ("total", "blank", "comment", "code")

DEFAULT_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".tox"}


def new_loc_bucket():
    return {"total": 0, "blank": 0, "comment": 0, "code": 0}


def add_loc_bucket(target, addition):
    for category in LOC_CATEGORIES:
        target[category] += addition[category]


# ---------------------------------------------------------------------------
# Comment-detection engine (per-language handlers), adapted from
# CommentRemoverV2_2.py -- used here purely to tell code from comments.
# ---------------------------------------------------------------------------


def restore_eof(original, cleaned):
    if original.endswith("\n") and not cleaned.endswith("\n"):
        return cleaned + "\n"
    if not original.endswith("\n") and cleaned.endswith("\n"):
        return cleaned.rstrip("\r\n")
    return cleaned


def preserve_newlines(match):
    return "".join(c for c in match.group(0) if c in "\r\n")


TRIPLE_QUOTES = ('"""', "'''")


def scan_hash_line(line, triple=None, preserve_hex_colors=False):
    """Strip a '#' comment from a single line.

    ``triple`` carries a still-open triple-quote delimiter ('\"\"\"' or
    \"'''\") from the previous line, so multi-line strings (Python
    docstrings, TOML multi-line strings, ...) are no longer mistaken for
    comment territory. Returns (cleaned_line, still_open_triple_or_None).
    """
    output, quote, escaped, index = [], None, False, 0
    length = len(line)
    while index < length:
        char = line[index]
        if triple:
            if line.startswith(triple, index):
                output.append(triple); index += len(triple); triple = None; continue
            output.append(char); index += 1; continue
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if char == "\\" and quote is not None:
            output.append(char); escaped = True; index += 1; continue
        if quote is None and line[index:index + 3] in TRIPLE_QUOTES:
            triple = line[index:index + 3]
            output.append(triple); index += 3; continue
        if char in ('"', "'"):
            quote = char if quote is None else (None if quote == char else quote)
            output.append(char); index += 1; continue
        if char == "#" and quote is None:
            if preserve_hex_colors:
                match = re.match(r"#[0-9A-Fa-f]{3,8}(?![0-9A-Fa-f])", line[index:])
                if match and line[:index].rstrip().endswith(("=", ":", "(", ",")):
                    output.append(match.group(0)); index += len(match.group(0)); continue
            break
        output.append(char); index += 1
    text = "".join(output)
    # Only trim trailing whitespace when we are *not* sitting inside an
    # still-open multi-line string - otherwise we would silently eat
    # trailing spaces that are part of the string's content.
    return (text if triple else text.rstrip()), triple


def remove_hash_comments(text):
    lines, triple = [], None
    for number, line in enumerate(text.splitlines()):
        if number == 0 and triple is None and line.startswith("#!"):
            lines.append(line); continue
        cleaned, triple = scan_hash_line(line, triple)
        lines.append(cleaned)
    return restore_eof(text, "\n".join(lines))


def remove_config_hash_comments(text):
    lines, triple = [], None
    for line in text.splitlines():
        cleaned, triple = scan_hash_line(line, triple, preserve_hex_colors=True)
        lines.append(cleaned)
    return restore_eof(text, "\n".join(lines))


def remove_yaml_comments(text):
    lines = []
    for line in text.splitlines():
        output, quote, escaped, index = [], None, False, 0
        while index < len(line):
            char = line[index]
            if escaped:
                output.append(char); escaped = False; index += 1; continue
            if quote:
                output.append(char)
                if quote == '"' and char == "\\": escaped = True
                elif char == quote:
                    if quote == "'" and index + 1 < len(line) and line[index + 1] == "'":
                        output.append("'"); index += 2; continue
                    quote = None
                index += 1; continue
            if char in ('"', "'"):
                quote = char; output.append(char); index += 1; continue
            if char != "#":
                output.append(char); index += 1; continue
            if index > 0 and not line[index - 1].isspace():
                output.append(char); index += 1; continue
            prefix, suffix = line[:index].rstrip(), line[index:]
            if re.fullmatch(r"#[^\s]+", suffix) and prefix.endswith((":", "=", "-")):
                output.append(suffix); index = len(line); continue
            break
        lines.append("".join(output).rstrip())
    return restore_eof(text, "\n".join(lines))


# ---------------------------------------------------------------------------
# C-like languages and Java
# ---------------------------------------------------------------------------


def remove_c_comments(text):
    output, index, quote, escaped = [], 0, None, False
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if quote:
            output.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            index += 1; continue
        if char in ('"', "'", "`"):
            quote = char; output.append(char); index += 1; continue
        if pair == "//":
            while index < len(text) and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < len(text):
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


def remove_java_comments(text):
    output, index, mode, escaped = [], 0, "code", False
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if mode == "text_block":
            if text.startswith('"""', index):
                output.append('"""'); index += 3; mode = "code"
            else: output.append(char); index += 1
            continue
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if mode in ("string", "char"):
            output.append(char)
            if char == "\\": escaped = True
            elif mode == "string" and char == '"': mode = "code"
            elif mode == "char" and char == "'": mode = "code"
            index += 1; continue
        if text.startswith('"""', index):
            output.append('"""'); index += 3; mode = "text_block"; continue
        if char == '"': mode = "string"; output.append(char); index += 1; continue
        if char == "'": mode = "char"; output.append(char); index += 1; continue
        if pair == "//":
            while index < len(text) and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < len(text):
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


# ---------------------------------------------------------------------------
# JavaScript, TypeScript, JSX and TSX
# ---------------------------------------------------------------------------


def remove_javascript_comments(text, preserve_jsx_comments=False):
    output = []
    index, length, mode = 0, len(text), "code"
    escaped, regex_class = False, False
    previous_significant, previous_word = None, ""
    regex_prefix_chars = set("=([{!?:;,<>+-*%&|^~")
    regex_prefix_words = {"return", "throw", "case", "delete", "typeof", "void", "new", "instanceof", "in", "of", "yield", "await", "else", "do"}

    def can_start_regex():
        return previous_significant is None or previous_significant in regex_prefix_chars or previous_word in regex_prefix_words

    while index < length:
        char, pair = text[index], text[index:index + 2]
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if mode in ("single", "double", "template"):
            output.append(char)
            if char == "\\": escaped = True
            elif (mode == "single" and char == "'") or (mode == "double" and char == '"') or (mode == "template" and char == "`"):
                mode = "code"; previous_significant, previous_word = char, ""
            index += 1; continue
        if mode == "regex":
            output.append(char)
            if char == "\\": escaped = True
            elif char == "[" and not regex_class: regex_class = True
            elif char == "]" and regex_class: regex_class = False
            elif char == "/" and not regex_class:
                mode = "code"; index += 1
                while index < length and (text[index].isalpha() or text[index].isdigit()):
                    output.append(text[index]); index += 1
                previous_significant, previous_word = "/", ""; continue
            index += 1; continue
        if char == "'": mode = "single"; output.append(char); index += 1; continue
        if char == '"': mode = "double"; output.append(char); index += 1; continue
        if char == "`": mode = "template"; output.append(char); index += 1; continue
        if preserve_jsx_comments and text.startswith("{/*", index):
            end = text.find("*/}", index + 3)
            if end == -1: output.append(text[index:]); break
            output.append(text[index:end + 3]); index = end + 3
            previous_significant, previous_word = "}", ""; continue
        if pair == "//":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < length:
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        if char == "/" and can_start_regex():
            mode = "regex"; regex_class = False; output.append(char); index += 1; continue
        output.append(char)
        if char.isalnum() or char in "_$": previous_word += char
        elif not char.isspace(): previous_significant, previous_word = char, ""
        index += 1
    return restore_eof(text, "".join(output))


def remove_jsx_comments(text):
    return remove_javascript_comments(text, preserve_jsx_comments=True)


# ---------------------------------------------------------------------------
# PHP, SQL, XML and Lua
# ---------------------------------------------------------------------------


def remove_php_comments(text):
    """Remove PHP comments while preserving Parsedown strings and escapes."""
    output, index, length = [], 0, len(text)
    in_php, quote = False, None
    while index < length:
        if not in_php and text.startswith("<?", index):
            in_php = True; output.append("<?"); index += 2; continue
        if not in_php:
            if text.startswith("<!--", index):
                index += 4
                while index < length:
                    if text.startswith("-->", index): index += 3; break
                    if text[index] in "\r\n": output.append(text[index])
                    index += 1
                continue
            output.append(text[index]); index += 1; continue
        char, pair = text[index], text[index:index + 2]
        if quote == "'":
            output.append(char)
            if char == "\\" and index + 1 < length and text[index + 1] in ("\\", "'"):
                output.append(text[index + 1]); index += 2; continue
            if char == "'": quote = None
            index += 1; continue
        if quote == '"':
            output.append(char)
            if char == "\\" and index + 1 < length:
                output.append(text[index + 1]); index += 2; continue
            if char == '"': quote = None
            index += 1; continue
        if char == "'": quote = "'"; output.append(char); index += 1; continue
        if char == '"': quote = '"'; output.append(char); index += 1; continue
        if pair == "?>": in_php = False; output.append(pair); index += 2; continue
        if pair == "//" or char == "#":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < length:
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


def remove_sql_comments(text):
    output, index, quote = [], 0, None
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    output.append(quote); index += 2; continue
                quote = None
            index += 1; continue
        if char in ('"', "'"): quote = char; output.append(char); index += 1; continue
        if pair == "--" or char == "#":
            while index < len(text) and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < len(text):
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


def remove_xml_comments(text):
    return restore_eof(text, re.sub(r"<!--.*?-->", preserve_newlines, text, flags=re.DOTALL))


def remove_lua_comments(text):
    output, index, length = [], 0, len(text)
    quote, escaped, long_end = None, False, None
    def bracket_end(pos):
        if pos >= length or text[pos] != "[": return None
        cursor = pos + 1
        while cursor < length and text[cursor] == "=": cursor += 1
        return "]" + text[pos + 1:cursor] + "]" if cursor < length and text[cursor] == "[" else None
    while index < length:
        char = text[index]
        if long_end:
            if text.startswith(long_end, index): output.append(long_end); index += len(long_end); long_end = None
            else: output.append(char); index += 1
            continue
        if escaped: output.append(char); escaped = False; index += 1; continue
        if quote:
            output.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            index += 1; continue
        if char in ('"', "'"): quote = char; output.append(char); index += 1; continue
        opening = bracket_end(index)
        if opening: output.append(text[index:index + len(opening)]); index += len(opening); long_end = opening; continue
        if text.startswith("--", index):
            index += 2; end = bracket_end(index)
            if end:
                index += len(end)
                while index < length:
                    if text.startswith(end, index): index += len(end); break
                    if text[index] in "\r\n": output.append(text[index])
                    index += 1
            else:
                while index < length and text[index] not in "\r\n": index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def decode_source_file(path):
    with open(path, "rb") as file: data = file.read()
    if data.startswith(b"\xef\xbb\xbf"): encoding, text = "utf-8-sig", data.decode("utf-8-sig")
    elif data.startswith(b"\xff\xfe\x00\x00"): encoding, text = "utf-32-le-bom", data[4:].decode("utf-32-le")
    elif data.startswith(b"\x00\x00\xfe\xff"): encoding, text = "utf-32-be-bom", data[4:].decode("utf-32-be")
    elif data.startswith(b"\xff\xfe"): encoding, text = "utf-16-le-bom", data[2:].decode("utf-16-le")
    elif data.startswith(b"\xfe\xff"): encoding, text = "utf-16-be-bom", data[2:].decode("utf-16-be")
    else:
        try: encoding, text = "utf-8", data.decode("utf-8")
        except UnicodeDecodeError:
            encoding = "cp1252" if any(0x80 <= b < 0xA0 for b in data) else "latin-1"
            text = data.decode(encoding)
    return text, encoding


# ---------------------------------------------------------------------------
# Handlers -- one comment-stripper per file extension
# ---------------------------------------------------------------------------

HANDLERS = {}
for ext in (".py", ".sh", ".toml", ".rb", ".tf"): HANDLERS[ext] = remove_hash_comments
for ext in (".yml", ".yaml"): HANDLERS[ext] = remove_yaml_comments
for ext in (".ini", ".cfg", ".conf", ".properties"): HANDLERS[ext] = remove_config_hash_comments
for ext in (".cs", ".c", ".cpp", ".cc", ".h", ".hpp", ".go", ".swift", ".kt", ".kts", ".css", ".scss", ".less", ".rs"): HANDLERS[ext] = remove_c_comments
HANDLERS[".java"] = remove_java_comments
for ext in (".js", ".ts", ".mjs", ".cjs", ".mts", ".cts"): HANDLERS[ext] = remove_javascript_comments
for ext in (".jsx", ".tsx"): HANDLERS[ext] = remove_jsx_comments
HANDLERS.update({".html": remove_xml_comments, ".htm": remove_xml_comments, ".php": remove_php_comments, ".sql": remove_sql_comments, ".xml": remove_xml_comments, ".xaml": remove_xml_comments, ".svg": remove_xml_comments, ".lua": remove_lua_comments})


# ---------------------------------------------------------------------------
# LoC classification and reporting
# ---------------------------------------------------------------------------


def classify_lines(source_text, stripped_text):
    """Classify every physical line of source_text as blank / comment-only / code.

    ``stripped_text`` must be the comment-stripped version of source_text with
    line positions preserved (as every handler above guarantees), so lines
    can be compared positionally: a line that was non-blank in the source
    but is blank after stripping was pure comment; everything else non-blank
    is real code (including code with a trailing comment removed).
    """
    source_lines = source_text.splitlines()
    stripped_lines = stripped_text.splitlines()
    bucket = new_loc_bucket()
    bucket["total"] = len(source_lines)
    for index, line in enumerate(source_lines):
        if line.strip() == "":
            bucket["blank"] += 1
        else:
            stripped_line = stripped_lines[index] if index < len(stripped_lines) else ""
            if stripped_line.strip() == "":
                bucket["comment"] += 1
            else:
                bucket["code"] += 1
    return bucket


def count_file(path):
    """Return the LoC bucket for a single file, or None if its type is unsupported."""
    filename = os.path.basename(path).lower()
    ext_key = "Dockerfile" if filename == "dockerfile" else os.path.splitext(filename)[1].lower()
    handler = remove_hash_comments if filename == "dockerfile" else HANDLERS.get(ext_key)
    if handler is None:
        return None, None
    try:
        text, _encoding = decode_source_file(path)
    except (OSError, UnicodeError) as error:
        print(f"WARNING: Could not decode: {path}\n         {error}", file=sys.stderr)
        return None, None
    stripped = handler(text)
    return ext_key, classify_lines(text, stripped)


def print_summary_table(by_extension, totals):
    if not by_extension:
        print("No supported source files found.")
        return
    categories = ("code", "comment", "blank", "total")
    exts = sorted(by_extension)
    ext_width = max(len("Type"), max(len(ext) for ext in exts))
    col_width = {category: max(len(category.capitalize()), 8) for category in categories}

    header = "  " + "Type".ljust(ext_width) + "   " + "   ".join(category.capitalize().rjust(col_width[category]) for category in categories)
    separator = "-" * len(header)
    print(header)
    print(separator)
    for ext in exts:
        bucket = by_extension[ext]
        row = "  " + ext.ljust(ext_width) + "   " + "   ".join(f"{bucket[category]:,}".rjust(col_width[category]) for category in categories)
        print(row)
    print(separator)
    total_row = "  " + "TOTAL".ljust(ext_width) + "   " + "   ".join(f"{totals[category]:,}".rjust(col_width[category]) for category in categories)
    print(total_row)


def main():
    parser = argparse.ArgumentParser(
        prog="loc.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            f"{PROGRAM_NAME} -- counts code / comment / blank lines per file "
            "and per file type. Read-only: never modifies, copies, or deletes "
            "any file.\n\n"
            f"{PROGRAM_SOURCE}"
        ),
        epilog=(
            "supported languages:\n"
            "  Python, Shell, TOML, Ruby, Terraform, YAML, INI/CFG/Properties,\n"
            "  C/C++/C#/Go/Swift/Kotlin/Rust/CSS/SCSS/LESS, Java, JavaScript/TypeScript\n"
            "  (incl. JSX/TSX), PHP, SQL, HTML/XML/XAML/SVG, Lua, Dockerfile"
        ),
    )
    parser.add_argument("-p", "--path", dest="path", metavar="PATH", required=True,
                         help="File or directory to analyze.")
    parser.add_argument("--include-hidden", action="store_true", dest="include_hidden",
                         help="Also descend into hidden directories (dot-directories) and "
                              "common dependency/build folders (.git, node_modules, venv, ...).")
    parser.add_argument("--per-file", action="store_true", dest="per_file",
                         help="Additionally print a line for every individual file, not just totals per type.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROGRAM_VERSION}")
    args = parser.parse_args()

    target = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.exists(target):
        print("ERROR: Path does not exist:", target, file=sys.stderr)
        return 1

    if os.path.isfile(target):
        all_files = [target]
    else:
        all_files = []
        for current, directories, files in os.walk(target):
            if not args.include_hidden:
                directories[:] = [name for name in directories if name not in DEFAULT_SKIP_DIRS and not name.startswith(".")]
            for name in files:
                all_files.append(os.path.join(current, name))

    by_extension = {}
    totals = new_loc_bucket()
    per_file_rows = []
    files_analyzed = 0

    for path in sorted(all_files):
        if os.path.islink(path):
            continue
        ext_key, bucket = count_file(path)
        if bucket is None:
            continue
        files_analyzed += 1
        add_loc_bucket(totals, bucket)
        ext_bucket = by_extension.setdefault(ext_key, new_loc_bucket())
        add_loc_bucket(ext_bucket, bucket)
        if args.per_file:
            relative = os.path.relpath(path, target) if os.path.isdir(target) else os.path.basename(path)
            per_file_rows.append((relative, bucket))

    print(f"{PROGRAM_NAME} v{PROGRAM_VERSION}")
    print(f"Path: {target}")
    print(f"Files analyzed: {files_analyzed}\n")

    if args.per_file and per_file_rows:
        print("Per-file breakdown:")
        name_width = max(len(name) for name, _ in per_file_rows)
        for name, bucket in per_file_rows:
            print(f"  {name.ljust(name_width)}   code {bucket['code']:>6,}   comment {bucket['comment']:>6,}   blank {bucket['blank']:>6,}   total {bucket['total']:>6,}")
        print()

    print_summary_table(by_extension, totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
