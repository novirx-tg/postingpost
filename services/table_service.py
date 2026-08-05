import re
from typing import List, Tuple, Any

def render_table(rows: List[List[str]], style: str = "box") -> str:
    """
    Renders a 2D matrix of text cells into a clean monospaced table string.
    
    Supported styles:
    - 'box': Beautiful Unicode box drawing characters (┌───┬───┐)
    - 'ascii': Standard ASCII borders (+---+---+)
    - 'simple': Minimalist header underline without vertical borders
    """
    if not rows:
        return ""

    # Normalize column counts
    max_cols = max(len(row) for row in rows)
    if max_cols == 0:
        return ""

    normalized_rows = [row + [""] * (max_cols - len(row)) for row in rows]
    
    # Calculate column widths (minimum width 1 char)
    col_widths = [0] * max_cols
    for row in normalized_rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell.strip()))
            
    col_widths = [max(w, 1) for w in col_widths]

    def pad_cell(val: str, width: int) -> str:
        return f" {val.strip().ljust(width)} "

    lines = []

    if style == "box":
        top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
        mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
        bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

        lines.append(top)
        for r_idx, row in enumerate(normalized_rows):
            row_str = "│" + "│".join(pad_cell(cell, col_widths[i]) for i, cell in enumerate(row)) + "│"
            lines.append(row_str)
            if r_idx == 0 and len(normalized_rows) > 1:
                lines.append(mid)
        lines.append(bot)

    elif style == "ascii":
        top_bot = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
        lines.append(top_bot)
        for r_idx, row in enumerate(normalized_rows):
            row_str = "|" + "|".join(pad_cell(cell, col_widths[i]) for i, cell in enumerate(row)) + "|"
            lines.append(row_str)
            if r_idx == 0 and len(normalized_rows) > 1:
                lines.append(top_bot)
        lines.append(top_bot)

    else:  # simple style
        for r_idx, row in enumerate(normalized_rows):
            row_str = "  ".join(cell.strip().ljust(col_widths[i]) for i, cell in enumerate(row))
            lines.append(row_str)
            if r_idx == 0 and len(normalized_rows) > 1:
                lines.append("  ".join("-" * col_widths[i] for i in range(max_cols)))

    return "\n".join(lines)


def parse_markdown_table(table_text: str) -> List[List[str]]:
    """
    Parses a markdown table block into a 2D list of row cells.
    Requires at least 2 table rows or a markdown delimiter line (|---|---|) to avoid false positives.
    """
    lines = [line.strip() for line in table_text.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return []

    has_delimiter = any(re.match(r'^[|\s:\-]+$', line) and '-' in line for line in lines)
    valid_pipe_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]

    if not has_delimiter and len(valid_pipe_lines) < 2:
        return []

    rows = []
    for line in lines:
        if not line.startswith("|") and not line.endswith("|"):
            if "|" not in line:
                continue

        content = line.strip("|").strip()
        if re.match(r'^[:\-\s|]+$', content):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)

    return rows if len(rows) >= 2 else []


def convert_markdown_tables_in_text(text: str, style: str = "box", format_html: bool = True) -> str:
    """
    Automatically converts genuine markdown table blocks in a text string into monospaced code table blocks.
    Leaves normal text and single pipe lines untouched.
    """
    if not text:
        return text

    table_block_pattern = re.compile(
        r'((?:^[ \t]*\|.*\|[ \t]*(?:\r?\n|$)){2,})',
        re.MULTILINE
    )

    def replace_table(match):
        raw_table = match.group(1)
        rows = parse_markdown_table(raw_table)
        if not rows or len(rows) < 2:
            return raw_table
        
        rendered = render_table(rows, style=style)
        if format_html:
            return f"<pre><code>{rendered}</code></pre>"
        else:
            return f"```\n{rendered}\n```"

    return table_block_pattern.sub(replace_table, text)


def create_tg_rich_table_payload(rows: List[List[str]], is_bordered: bool = True, is_striped: bool = True) -> dict:
    """
    Creates Telegram Bot API 10.1+ InputRichBlockTable block structure for native tables.
    """
    table_cells = []
    for row in rows:
        row_cells = []
        for cell_text in row:
            row_cells.append({"text": str(cell_text).strip()})
        table_cells.append(row_cells)

    return {
        "type": "table",
        "is_bordered": is_bordered,
        "is_striped": is_striped,
        "cells": table_cells
    }


async def send_tg_rich_table(bot: Any, chat_id: int, text: str, rows: List[List[str]], reply_markup: Any = None) -> Tuple[bool, Any]:
    """
    Attempts to send a native Telegram Rich Message table using sendRichMessage (Bot API 10.1+).
    Falls back seamlessly to HTML monospaced preformatted code table if sendRichMessage is unsupported.
    """
    rich_table_block = create_tg_rich_table_payload(rows, is_bordered=True, is_striped=True)
    
    blocks = []
    if text:
        blocks.append({"type": "paragraph", "text": text})
    blocks.append(rich_table_block)

    payload = {
        "chat_id": chat_id,
        "rich_message": {
            "blocks": blocks
        }
    }

    if reply_markup:
        if hasattr(reply_markup, "model_dump"):
            payload["reply_markup"] = reply_markup.model_dump(exclude_none=True)
        elif hasattr(reply_markup, "to_python"):
            payload["reply_markup"] = reply_markup.to_python()

    try:
        result = await bot.session.make_request(bot.token, "sendRichMessage", payload)
        return True, result
    except Exception:
        box_table = render_table(rows, style="box")
        fallback_text = f"{text}\n\n<pre><code>{box_table}</code></pre>" if text else f"<pre><code>{box_table}</code></pre>"
        msg = await bot.send_message(chat_id=chat_id, text=fallback_text, parse_mode="HTML", reply_markup=reply_markup)
        return False, msg


def extract_text_and_table_from_message(message: Any) -> Tuple[str, List[List[str]]]:
    """
    Extracts text and native RichBlockTable from an incoming Telegram message object.
    Handles standard text, captions, and Telegram Bot API 10.1+ rich_message objects.
    """
    extracted_text_parts = []
    extracted_table = []

    # 1. Standard text or caption
    main_text = getattr(message, "html_text", None) or getattr(message, "text", None) or getattr(message, "caption", None)
    if main_text:
        extracted_text_parts.append(main_text)

    # 2. Check for rich_message payload (Bot API 10.1+)
    rich_msg = getattr(message, "rich_message", None)
    if not rich_msg and hasattr(message, "model_extra") and isinstance(message.model_extra, dict):
        rich_msg = message.model_extra.get("rich_message")

    if rich_msg:
        blocks = getattr(rich_msg, "blocks", None)
        if not blocks and isinstance(rich_msg, dict):
            blocks = rich_msg.get("blocks")

        if blocks and isinstance(blocks, list):
            for block in blocks:
                b_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                if b_type == "table":
                    cells = getattr(block, "cells", None) or (block.get("cells") if isinstance(block, dict) else None)
                    if cells and isinstance(cells, list):
                        for row in cells:
                            row_texts = []
                            for cell in row:
                                c_text = getattr(cell, "text", None) or (cell.get("text") if isinstance(cell, dict) else str(cell))
                                row_texts.append(str(c_text))
                            extracted_table.append(row_texts)
                elif b_type in ("paragraph", "text", "quote", "heading"):
                    b_text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "")
                    if b_text and b_text not in extracted_text_parts:
                        extracted_text_parts.append(str(b_text))

    if extracted_table:
        table_str = "\n".join([" | ".join(row) for row in extracted_table])
        if table_str and table_str not in extracted_text_parts:
            extracted_text_parts.append(table_str)

    combined_text = "\n\n".join([t for t in extracted_text_parts if t])
    return combined_text, extracted_table
